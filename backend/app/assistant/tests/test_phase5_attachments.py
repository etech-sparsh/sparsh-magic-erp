"""Phase 5 verification — multi-modal attachments. No live DB / OpenAI / S3 needed.

Covers: upload validation (block/allow/oversize/sanitize), content extraction
(code / text / zip + zip-slip guard), attachment-context building (text cap +
vision images + persisted metas + retrieval hint), and the orchestrator emitting
a multi-modal user turn (vision image block) when attachments are present.

Run:  python -m app.assistant.tests.test_phase5_attachments   (from backend/)
"""
from __future__ import annotations

import asyncio
import io
import os
import tempfile
import zipfile

from bson import ObjectId

from app.assistant.config import config
from app.assistant.files import attachment_store, extractor
from app.assistant.files import service as attachment_service
from app.assistant.files.service import ValidationError, validate
from app.assistant.schemas.context import UserContext

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' - ' + extra) if extra else ''}")


class _UF:
    """Minimal UploadFile stand-in for validate()."""

    def __init__(self, filename, content_type="application/octet-stream", size=10):
        self.filename = filename
        self.content_type = content_type
        self.size = size


USER = UserContext(user_id="U1", full_name="Asha", role="clientuser", company_id="C1")


async def test_validation():
    print("Validation & security:")
    for bad, label in [("malware.exe", "blocked .exe rejected"),
                       ("evil.bat", "blocked .bat rejected"),
                       ("weird.xyz", "unsupported ext rejected")]:
        try:
            validate(_UF(bad))
            check(label, False)
        except ValidationError:
            check(label, True)

    try:
        validate(_UF("big.pdf", "application/pdf",
                     size=(config.MAX_FILE_SIZE_MB + 1) * 1024 * 1024))
        check("oversize rejected", False)
    except ValidationError:
        check("oversize rejected", True)

    check("valid pdf accepted", validate(_UF("report.pdf", "application/pdf", 100)) == "report.pdf")
    check("path traversal sanitized to basename",
          validate(_UF("../../etc/passwd.txt", "text/plain", 10)) == "passwd.txt")


async def test_extractor():
    print("\nExtraction:")
    check("kind classification", extractor.kind_of("a.py") == "code"
          and extractor.kind_of("a.pdf") == "document"
          and extractor.kind_of("a.png") == "image"
          and extractor.kind_of("a.zip") == "archive")

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("def add(a, b):\n    return a + b\n")
        py = f.name
    res = await extractor.extract(py, "math.py")
    os.remove(py)
    check("code fenced with language hint", "```python" in res["text"] and "def add" in res["text"])

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("hello world deadlines payment terms")
        tx = f.name
    res = await extractor.extract(tx, "notes.txt")
    os.remove(tx)
    check("txt extracted (via shared extractor)", "payment terms" in res["text"], res["text"][:80])

    # ZIP: structure listing + inner-file extraction.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("src/app.py", "print('hi from zip')\n")
        z.writestr("README.md", "# Project\nsetup instructions")
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(buf.getvalue())
        zp = f.name
    res = await extractor.extract(zp, "project.zip")
    os.remove(zp)
    check("zip lists structure", "Archive structure" in res["text"] and "src/app.py" in res["text"])
    check("zip extracts inner files",
          "hi from zip" in res["text"] or "setup instructions" in res["text"])

    # zip-slip guard: malicious "../" entries must be filtered out.
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w") as z:
        z.writestr("../evil.txt", "pwned")
        z.writestr("ok.txt", "safe")
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(buf2.getvalue())
        zp2 = f.name
    with zipfile.ZipFile(zp2) as zf:
        safe = extractor._safe_zip_members(zf)
    os.remove(zp2)
    check("zip-slip entry filtered",
          all(".." not in m.filename.replace("\\", "/").split("/") for m in safe))


async def test_context_building():
    print("\nAttachment context building:")
    oid = ObjectId()
    doc = {
        "_id": oid, "uploaded_by": "U1", "filename": "contract.pdf", "kind": "document",
        "mime_type": "application/pdf", "size": 1234, "status": "completed",
        "extracted_text": "Final project cost is 50000 USD. " * 5,
        "images": ["data:image/png;base64,AAAA"], "summary": "A contract.",
    }

    async def fake_get_many(ctx, ids):
        return [doc]

    async def fake_link(ctx, ids, cid):
        return None

    async def fake_ensure(cid, aid, filename, text):
        return None

    attachment_store.get_many_for_user = fake_get_many
    attachment_store.link_to_conversation = fake_link
    attachment_store.ensure_chunks_for_conversation = fake_ensure

    out = await attachment_service.build_attachment_context(USER, [str(oid)], "CONV1")
    check("text block names the file", "contract.pdf" in out["text_block"])
    check("text block carries content", "Final project cost" in out["text_block"])
    check("image surfaced for vision", out["images"] == ["data:image/png;base64,AAAA"])
    check("meta has id + filename",
          out["metas"][0]["id"] == str(oid) and out["metas"][0]["filename"] == "contract.pdf")
    check("retrieval hint includes conversation id", "CONV1" in out["text_block"])

    big = dict(doc, extracted_text="x" * (config.MAX_EXTRACTED_CHARS_PER_FILE + 100), images=[])

    async def fake_get_big(ctx, ids):
        return [big]

    attachment_store.get_many_for_user = fake_get_big
    out2 = await attachment_service.build_attachment_context(USER, [str(oid)], "CONV1")
    check("over-cap text truncated with note", "truncated" in out2["text_block"])

    # No attachments -> empty context (text-only path unchanged).
    none = await attachment_service.build_attachment_context(USER, None, "CONV1")
    check("no attachments -> empty context",
          none["text_block"] == "" and none["images"] == [] and none["metas"] == [])


async def test_orchestrator_injection():
    print("\nOrchestrator multi-modal turn:")
    import app.assistant.memory.conversation_store as store
    from app.assistant.core import query_rewriter
    from app.assistant.core.orchestrator import Orchestrator

    # In-memory conversation doc so load_or_create / append_turn work.
    convo_doc = {"_id": ObjectId(), "user_id": "U1", "role": "clientuser", "title": None,
                 "summary": None, "summary_upto": 0, "messages": [], "message_count": 0}

    class _Coll:
        async def create_index(self, *a, **k):
            return "idx"

        async def find_one(self, q):
            return convo_doc

        async def insert_one(self, d):
            class R:
                inserted_id = convo_doc["_id"]
            return R()

        async def update_one(self, f, u):
            for k, v in u.get("$set", {}).items():
                convo_doc[k] = v
            for k, v in u.get("$push", {}).items():
                convo_doc.setdefault(k, []).extend(v["$each"] if isinstance(v, dict) else [v])
            class R:
                modified_count = 1
            return R()

    store.get_collection = lambda name: _Coll()
    store._indexes_ready = True

    # Skip the rewrite LLM call.
    async def _no_rewrite(llm, message, summary="", recent="", meter=None):
        return {"rewritten": False, "rewritten_query": message}
    query_rewriter.rewrite = _no_rewrite

    # Force an attachment context with an image so we can assert vision blocks.
    async def _ctx(ctx, ids, cid, query=""):
        return {"text_block": "\n\n[Attached files]\n## a.png (image)\n",
                "images": ["data:image/png;base64,ZZZ"],
                "metas": [{"id": "att1", "filename": "a.png", "kind": "image"}]}
    attachment_service.build_attachment_context = _ctx

    # Minimal fake LLM that just answers.
    class FakeUsage:
        prompt_tokens = 10
        completion_tokens = 5
        total_tokens = 15

    class _Msg:
        def __init__(self, content):
            self.content = content
            self.tool_calls = None

    captured = {}

    class FakeLLM:
        async def complete(self, messages, tools=None, max_tokens=None, meter=None):
            captured["messages"] = messages
            if meter:
                meter.add(FakeUsage())
            return _Msg("Seen the image.")

        async def utility_complete(self, prompt, max_tokens=120, meter=None):
            return "Img Chat"

        async def summarize(self, text, meter=None):
            return "s"

    orch = Orchestrator(llm=FakeLLM())
    resp = await orch.handle_message(USER, "what's in this image?", attachment_ids=["att1"])

    user_msg = next(m for m in captured["messages"] if m["role"] == "user")
    is_list = isinstance(user_msg["content"], list)
    has_image = is_list and any(p.get("type") == "image_url" for p in user_msg["content"])
    check("user turn is multi-modal (content is a list)", is_list)
    check("vision image_url block present", has_image)
    check("answer returned normally", resp.answer == "Seen the image.")
    persisted_user = next(m for m in convo_doc["messages"] if m["role"] == "user")
    check("attachment meta persisted on user turn",
          bool(persisted_user.get("attachments")) and persisted_user["attachments"][0]["filename"] == "a.png")


async def test_empty_message_defaults_to_summary():
    print("\nAttachments-only turn (empty message):")
    import app.assistant.memory.conversation_store as store
    from app.assistant.core import query_rewriter
    from app.assistant.core.orchestrator import Orchestrator

    convo_doc = {"_id": ObjectId(), "user_id": "U1", "role": "clientuser", "title": None,
                 "summary": None, "summary_upto": 0, "messages": [], "message_count": 0}

    class _Coll:
        async def create_index(self, *a, **k):
            return "idx"

        async def find_one(self, q):
            return convo_doc

        async def insert_one(self, d):
            class R:
                inserted_id = convo_doc["_id"]
            return R()

        async def update_one(self, f, u):
            for k, v in u.get("$set", {}).items():
                convo_doc[k] = v
            for k, v in u.get("$push", {}).items():
                convo_doc.setdefault(k, []).extend(v["$each"] if isinstance(v, dict) else [v])
            class R:
                modified_count = 1
            return R()

    store.get_collection = lambda name: _Coll()
    store._indexes_ready = True

    # Record whether the rewriter is invoked — it must be skipped for an
    # empty, attachment-only turn (otherwise it hallucinates a question).
    rewrite_called = {"hit": False}

    async def _spy_rewrite(llm, message, summary="", recent="", meter=None):
        rewrite_called["hit"] = True
        return {"rewritten": False, "rewritten_query": message}
    query_rewriter.rewrite = _spy_rewrite

    async def _ctx(ctx, ids, cid, query=""):
        return {"text_block": "\n\n[Attached files]\n## report.pdf (document)\nbody text\n",
                "images": [],
                "metas": [{"id": "att1", "filename": "report.pdf", "kind": "document"}]}
    attachment_service.build_attachment_context = _ctx

    class FakeUsage:
        prompt_tokens = 10
        completion_tokens = 5
        total_tokens = 15

    class _Msg:
        def __init__(self, content):
            self.content = content
            self.tool_calls = None

    captured = {}

    class FakeLLM:
        async def complete(self, messages, tools=None, max_tokens=None, meter=None):
            captured["messages"] = messages
            if meter:
                meter.add(FakeUsage())
            return _Msg("Here is a summary.")

        async def utility_complete(self, prompt, max_tokens=120, meter=None):
            return "Report"

        async def summarize(self, text, meter=None):
            return "s"

    orch = Orchestrator(llm=FakeLLM())
    resp = await orch.handle_message(USER, "", attachment_ids=["att1"])

    user_msg = next(m for m in captured["messages"] if m["role"] == "user")
    text = user_msg["content"] if isinstance(user_msg["content"], str) else \
        next(p["text"] for p in user_msg["content"] if p.get("type") == "text")
    check("rewriter skipped for empty attachment turn", not rewrite_called["hit"])
    check("default summary instruction injected",
          config.DEFAULT_ATTACHMENT_PROMPT in text, text[:80])
    check("attachment content still present", "report.pdf" in text)
    check("answer returned normally", resp.answer == "Here is a summary.")


async def main():
    print("\n=== Phase 5 Multi-Modal Attachments Verification ===\n")
    await test_validation()
    await test_extractor()
    await test_context_building()
    await test_orchestrator_injection()
    await test_empty_message_defaults_to_summary()
    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
