"""HRMS ▸ HR Letter / Document Generator (BA/Functional Design §41, screen SM-HR-041).

Offer and Appointment letters already exist elsewhere in this module and are deliberately
HTML-only, regenerated on demand from the live offer/appointment record — correct for those
two, since the record IS the source of truth and a stored copy would just be free to drift.
This service is for every OTHER piece of controlled employee correspondence (confirmation,
revision, warning, relieving, and whatever else HR needs) where there is no other record to
regenerate from: the letter's rendered content is itself the thing that must be kept, so it
is actually produced as a PDF, stored, and made immutable once issued.

-- Reuses three things already proven elsewhere in this module, invents none -----------------
  * The merge-field engine is `render_comm_body` (models/hrms.py) — the exact `{field}`
    `format_map` convention Offer/Appointment/Comm already use. No second templating syntax.
  * The PDF stack is ReportLab Platypus, the same one hrms_record_document_service.py uses —
    that module's own docstring already explains why a second stack (WeasyPrint/wkhtmltopdf)
    buys nothing here either.
  * Storage is S3 + a signed URL, the same pattern hrms_document_service.py and
    hrms_record_document_service.py both use — unlike the record-document prints (generated
    fresh every request, never kept), a letter's PDF IS kept: `s3_key` is stored on the
    document and a fresh signed URL is minted on every read, since the URL itself expires but
    the object must not.

-- Immutability is enforced by STATE, not by field-level guards ------------------------------
Draft -> Issued -> (optionally) Superseded. Only a Draft's content can be replaced (by calling
`generate` again with the same inputs) because nothing official has been produced yet. Once
Issued, nothing about that row is ever written again -- a correction is a `reissue`, which
supersedes the old row and creates a new one. This is the literal BA rule: "Generated file
immutable; new version for change."

-- No seeded templates ------------------------------------------------------------------------
Unlike the six candidate-communication templates this module already ships defaults for,
letter templates start empty. A confirmation letter's exact clauses and a warning letter's
language are company- and jurisdiction-specific; putting invented legal wording in front of a
real employee is a materially worse default than an empty list HR fills in themselves.
"""
import io
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_LETTER_GENERATED, AUDIT_LETTER_ISSUED, AUDIT_LETTER_REISSUED,
    AUDIT_LETTER_TEMPLATE_SAVED, COLL_EMPLOYEE_PROFILES, COLL_LETTER_TEMPLATES, COLL_LETTERS,
    DOCUMENT_URL_TTL_SECONDS, ENTITY_LETTER, ENTITY_LETTER_TEMPLATE,
    HrmsRole, LetterStatus, render_comm_body,
)
from app.services import hrms_employee_service as employees
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import hrms_role


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _actor_id(actor: dict) -> str:
    return str((actor or {}).get("_id") or "")


def _actor_name(actor: dict) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "an HRMS user")


async def _own_employee_code(actor: dict, company_id: str) -> Optional[str]:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "user_id": _actor_id(actor)})
    return (profile or {}).get("employee_code")


async def _scope_query(actor: dict, company_id: str, query: dict) -> dict:
    """An EMPLOYEE caller (LETTER_READ only) sees just their own correspondence; every other
    role holding LETTER_READ sees the company's. Fails CLOSED, the same PIP/ATT-1 pattern."""
    if hrms_role(actor) == HrmsRole.EMPLOYEE:
        own = await _own_employee_code(actor, company_id)
        query["employee_code"] = own or "__none__"
    return query


# =============================================================
# Templates
# =============================================================
async def list_templates(company_id: str, *, include_inactive: bool = False) -> list:
    query = {"company_id": str(company_id)}
    if not include_inactive:
        query["active"] = True
    rows = await get_collection(COLL_LETTER_TEMPLATES).find(query).sort("key", 1).to_list(200)
    return [_out(r) for r in rows]


async def get_template(company_id: str, key: str) -> Optional[dict]:
    doc = await get_collection(COLL_LETTER_TEMPLATES).find_one(
        {"company_id": str(company_id), "key": key})
    return _out(doc) if doc else None


async def save_template(actor: dict, company_id: str, key: str, payload: dict) -> dict:
    """Create the template on first use of `key`, otherwise edit it in place — templates are
    HR's own working copy, not a controlled artifact themselves (see the phase's module
    docstring for why the ISSUED LETTER is what must be immutable, not the template)."""
    key = (key or "").strip().lower().replace(" ", "_")
    if not key:
        raise HTTPException(status_code=422, detail="A template needs a key.")

    coll = get_collection(COLL_LETTER_TEMPLATES)
    current = await coll.find_one({"company_id": str(company_id), "key": key})
    now = datetime.now(timezone.utc)

    title = (payload.get("title") or "").strip()
    body = payload.get("body") or ""
    if not title or not str(body).strip():
        raise HTTPException(status_code=422, detail="A template needs a title and a body.")

    doc = {
        "company_id": str(company_id),
        "key": key,
        "title": title,
        "body": body,
        "merge_fields": list(payload.get("merge_fields") or []),
        "active": bool(payload.get("active", True)),
        "version": (current or {}).get("version", 0) + 1,
        "updated_at": now,
        "updated_by": _actor_id(actor),
    }
    if current:
        await coll.update_one({"_id": current["_id"]}, {"$set": doc})
    else:
        doc["created_at"] = now
        await coll.insert_one(doc)
    await audit(actor, AUDIT_LETTER_TEMPLATE_SAVED, ENTITY_LETTER_TEMPLATE, key, title, company_id)
    return await get_template(company_id, key)


# =============================================================
# Merge fields
# =============================================================
async def _resolve_employee(actor: dict, company_id: str, employee_code: str) -> dict:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    if not profile:
        raise HTTPException(
            status_code=404, detail=f"No employee '{employee_code}' in this company.")
    user_id = profile.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=409,
            detail=f"{employee_code} has no linked login yet — link their account before "
                   f"generating correspondence for them.")
    return await employees.get_employee(actor, user_id, company_id=company_id)


def _merge_fields(emp: dict, *, effective_date: Optional[str], approver_name: Optional[str],
                  approver_designation: Optional[str], extra: dict) -> dict:
    now = datetime.now(timezone.utc)
    values = {
        "employee_name": emp.get("name") or "",
        "employee_code": emp.get("employee_code") or "",
        "designation": emp.get("designation") or "",
        "department": emp.get("department") or "",
        "joining_date": emp.get("joined_on") or "",
        "email": emp.get("email") or "",
        "effective_date": effective_date or now.strftime("%Y-%m-%d"),
        "approver_name": approver_name or "",
        "approver_designation": approver_designation or "",
        "today": now.strftime("%d %b %Y"),
    }
    # Derived facts win — an extra field can ADD something the record cannot supply (a new
    # designation on a revision letter, a warning's reason), it may never override a fact
    # already read from the employee's own record.
    for k, v in (extra or {}).items():
        if k in values and values[k]:
            continue
        values[k] = "" if v is None else str(v)
    return values


# =============================================================
# Rendering
# =============================================================
def _render_letter_pdf(*, company_name: str, letter_no: str, title: str, body: str,
                       employee_name: str, designation: str, effective_date: str,
                       approver_name: str, approver_designation: str,
                       generated_by: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    body_style = ParagraphStyle("letter_body", parent=styles["BodyText"], fontSize=10.5,
                                leading=15, spaceAfter=8)
    meta_style = ParagraphStyle("letter_meta", parent=body_style, fontSize=9.5,
                                textColor=colors.HexColor("#555555"))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=25 * mm, rightMargin=25 * mm, topMargin=22 * mm, bottomMargin=20 * mm,
        title=f"{title} — {letter_no}", author=company_name or "Sparsh Magic")

    flow = [
        Paragraph(f"<b>{company_name or 'Sparsh Magic'}</b>",
                  ParagraphStyle("letter_head", parent=styles["Heading1"], fontSize=14)),
        Spacer(1, 8 * mm),
        Paragraph(f"Date: {effective_date}", meta_style),
        Paragraph(f"Ref: {letter_no}", meta_style),
        Spacer(1, 4 * mm),
        Paragraph(f"To,<br/><b>{employee_name}</b><br/>{designation or ''}", body_style),
        Spacer(1, 4 * mm),
        Paragraph(f"<b>Subject: {title}</b>", body_style),
        Spacer(1, 4 * mm),
    ]

    # Blank-line-separated paragraphs, single newlines as a line break within one — the same
    # "operator wrote plain text, keep their line breaks" treatment the offer/appointment
    # bodies already get from the browser rendering them as HTML.
    for para in (body or "").split("\n\n"):
        html_para = para.strip().replace("\n", "<br/>")
        if html_para:
            flow.append(Paragraph(html_para, body_style))

    flow += [
        Spacer(1, 10 * mm),
        Paragraph(
            f"{approver_name or '________________'}<br/>{approver_designation or ''}",
            body_style),
        Spacer(1, 8 * mm),
        Paragraph(
            f"Generated from HRMS on "
            f'{datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")} by {generated_by}.',
            meta_style),
    ]
    doc.build(flow)
    return buffer.getvalue()


async def _company_name(company_id: str) -> str:
    try:
        row = await get_collection("companies").find_one(
            {"_id": ObjectId(str(company_id))}, {"name": 1, "company_name": 1})
        return (row or {}).get("name") or (row or {}).get("company_name") or ""
    except Exception:
        return ""


async def _store_pdf(pdf: bytes, letter_no: str) -> tuple:
    from app.services.s3_service import upload_file_to_s3_with_key
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    try:
        result = upload_file_to_s3_with_key(
            io.BytesIO(pdf), f"hrms_letter_{letter_no}_{stamp}.pdf", "application/pdf")
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"The letter could not be generated right now. ({e})")
    key = result.get("key") if isinstance(result, dict) else None
    if not key:
        raise HTTPException(status_code=503, detail="The letter could not be generated right now.")
    return key


def _signed_url(s3_key: Optional[str]) -> Optional[str]:
    if not s3_key:
        return None
    from app.services.s3_service import get_signed_url
    return get_signed_url(s3_key, expires_in=DOCUMENT_URL_TTL_SECONDS)


async def _render_and_store(actor: dict, company_id: str, template: dict, emp: dict,
                            merge: dict, letter_no: str) -> tuple:
    rendered_body = render_comm_body(template.get("body") or "", merge)
    company_name = await _company_name(company_id)
    pdf = _render_letter_pdf(
        company_name=company_name, letter_no=letter_no, title=template.get("title") or "",
        body=rendered_body, employee_name=merge.get("employee_name"),
        designation=merge.get("designation"), effective_date=merge.get("effective_date"),
        approver_name=merge.get("approver_name"),
        approver_designation=merge.get("approver_designation"),
        generated_by=_actor_name(actor))
    s3_key = await _store_pdf(pdf, letter_no)
    return rendered_body, s3_key


# =============================================================
# Preview / generate / issue / reissue
# =============================================================
async def preview_letter(actor: dict, company_id: str, payload: dict) -> dict:
    """No persistence, no file — a pure render so HR can see the letter before committing."""
    template = await get_template(company_id, payload.get("template_key"))
    if not template:
        raise HTTPException(
            status_code=422, detail=f"There is no '{payload.get('template_key')}' template.")
    emp = await _resolve_employee(actor, company_id, payload.get("employee_code"))
    merge = _merge_fields(
        emp, effective_date=payload.get("effective_date"),
        approver_name=payload.get("approver_name"),
        approver_designation=payload.get("approver_designation"),
        extra=payload.get("extra_fields") or {})
    return {
        "template_key": template["key"], "title": template["title"],
        "rendered_body": render_comm_body(template.get("body") or "", merge),
        "merge_fields": merge,
    }


async def generate_letter(actor: dict, company_id: str, payload: dict) -> dict:
    """SM-HR-041's "generate" action — produces a Draft. A Draft is still regenerable: call
    this again with the same letter_no's inputs before `issue` and the content is replaced,
    because nothing official has been produced from it yet."""
    template_key = payload.get("template_key")
    template = await get_template(company_id, template_key)
    if not template:
        raise HTTPException(status_code=422, detail=f"There is no '{template_key}' template.")
    if not template.get("active"):
        raise HTTPException(
            status_code=422, detail=f"The '{template_key}' template is not active.")

    employee_code = payload.get("employee_code")
    emp = await _resolve_employee(actor, company_id, employee_code)
    merge = _merge_fields(
        emp, effective_date=payload.get("effective_date"),
        approver_name=payload.get("approver_name"),
        approver_designation=payload.get("approver_designation"),
        extra=payload.get("extra_fields") or {})

    existing_no = payload.get("letter_no")
    if existing_no:
        old = await _get_letter(company_id, existing_no)
        if old["status"] != LetterStatus.DRAFT.value:
            raise HTTPException(
                status_code=409,
                detail=f"{existing_no} is already \"{old['status']}\" — a draft can be "
                       f"regenerated, an issued letter can only be reissued.")
        letter_no = existing_no
        series_no = old["series_no"]
        created_at = old["created_at"]     # regeneration is not a new creation
    else:
        year = datetime.now(timezone.utc).year
        letter_no = await next_business_id("letter", str(company_id), year)
        series_no = letter_no          # the first letter in its own reissue chain
        created_at = datetime.now(timezone.utc)

    rendered_body, s3_key = await _render_and_store(actor, company_id, template, emp, merge, letter_no)

    now = datetime.now(timezone.utc)
    doc = {
        "letter_no": letter_no,
        "series_no": series_no,
        "supersedes": None,
        "superseded_by": None,
        "version": 1,
        "company_id": str(company_id),
        "template_key": template_key,
        "template_version": template.get("version"),
        "employee_code": employee_code,
        "employee_name": emp.get("name"),
        "title": template.get("title"),
        "rendered_body": rendered_body,
        "merge_fields": merge,
        "s3_key": s3_key,
        "status": LetterStatus.DRAFT.value,
        "generated_by": _actor_id(actor), "generated_at": now,
        "issued_by": None, "issued_at": None,
        "reason": None,
        "created_at": created_at, "updated_at": now,
    }
    await get_collection(COLL_LETTERS).update_one(
        {"company_id": str(company_id), "letter_no": letter_no}, {"$set": doc}, upsert=True)
    await audit(actor, AUDIT_LETTER_GENERATED, ENTITY_LETTER, letter_no,
               f"{template_key} for {employee_code}", company_id)
    return await get_letter(actor, company_id, letter_no)


async def _get_letter(company_id: str, letter_no: str) -> dict:
    doc = await get_collection(COLL_LETTERS).find_one(
        {"company_id": str(company_id), "letter_no": letter_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Letter '{letter_no}' not found.")
    return doc


async def get_letter(actor: dict, company_id: str, letter_no: str) -> dict:
    doc = await _get_letter(company_id, letter_no)
    if hrms_role(actor) == HrmsRole.EMPLOYEE:
        own = await _own_employee_code(actor, company_id)
        if own != doc["employee_code"]:
            raise HTTPException(status_code=403, detail="You may only view your own correspondence.")
    out = _out(doc)
    out["url"] = _signed_url(doc.get("s3_key"))
    return out


async def list_letters(actor: dict, company_id: str, *, employee_code: Optional[str] = None,
                       status: Optional[str] = None, limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if employee_code:
        query["employee_code"] = employee_code
    if status:
        query["status"] = status
    query = await _scope_query(actor, company_id, query)
    rows = await get_collection(COLL_LETTERS).find(query).sort("created_at", -1).to_list(min(limit, 500))
    out = []
    for r in rows:
        row = _out(r)
        row["url"] = _signed_url(r.get("s3_key"))
        out.append(row)
    return out


async def issue_letter(actor: dict, company_id: str, letter_no: str) -> dict:
    """SM-HR-041's "issue" action — the point of no return. From here the row is never
    written again; a correction is a `reissue`."""
    doc = await _get_letter(company_id, letter_no)
    if doc["status"] != LetterStatus.DRAFT.value:
        raise HTTPException(status_code=409, detail=f"{letter_no} is already \"{doc['status']}\".")

    now = datetime.now(timezone.utc)
    await get_collection(COLL_LETTERS).update_one(
        {"_id": doc["_id"]},
        {"$set": {"status": LetterStatus.ISSUED.value, "issued_by": _actor_id(actor),
                  "issued_at": now, "updated_at": now}})
    await audit(actor, AUDIT_LETTER_ISSUED, ENTITY_LETTER, letter_no, None, company_id)
    return await get_letter(actor, company_id, letter_no)


async def reissue_letter(actor: dict, company_id: str, letter_no: str, payload: dict) -> dict:
    """SM-HR-041's "reissue" action. The old row becomes Superseded (content untouched,
    retained for audit — "system retains superseded versions" is the same rule the HR Policy
    Library below states explicitly); a NEW letter is issued directly, since a reissue is
    invoked with the final content already decided rather than needing its own preview cycle
    (preview is available beforehand, statelessly, for any content HR wants to check first)."""
    old = await _get_letter(company_id, letter_no)
    if old["status"] != LetterStatus.ISSUED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Only an Issued letter can be reissued (this one is \"{old['status']}\").")
    reason = (payload.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A reissue needs a reason.")

    template_key = payload.get("template_key") or old["template_key"]
    template = await get_template(company_id, template_key)
    if not template:
        raise HTTPException(status_code=422, detail=f"There is no '{template_key}' template.")

    employee_code = payload.get("employee_code") or old["employee_code"]
    emp = await _resolve_employee(actor, company_id, employee_code)
    merge = _merge_fields(
        emp, effective_date=payload.get("effective_date"),
        approver_name=payload.get("approver_name"),
        approver_designation=payload.get("approver_designation"),
        extra=payload.get("extra_fields") or {})

    year = datetime.now(timezone.utc).year
    new_no = await next_business_id("letter", str(company_id), year)
    rendered_body, s3_key = await _render_and_store(actor, company_id, template, emp, merge, new_no)

    now = datetime.now(timezone.utc)
    new_doc = {
        "letter_no": new_no,
        "series_no": old.get("series_no") or old["letter_no"],
        "supersedes": letter_no,
        "superseded_by": None,
        "version": (old.get("version") or 1) + 1,
        "company_id": str(company_id),
        "template_key": template_key,
        "template_version": template.get("version"),
        "employee_code": employee_code,
        "employee_name": emp.get("name"),
        "title": template.get("title"),
        "rendered_body": rendered_body,
        "merge_fields": merge,
        "s3_key": s3_key,
        "status": LetterStatus.ISSUED.value,
        "generated_by": _actor_id(actor), "generated_at": now,
        "issued_by": _actor_id(actor), "issued_at": now,
        "reason": reason,
        "created_at": now, "updated_at": now,
    }
    await get_collection(COLL_LETTERS).insert_one(new_doc)
    await get_collection(COLL_LETTERS).update_one(
        {"_id": old["_id"]},
        {"$set": {"status": LetterStatus.SUPERSEDED.value, "superseded_by": new_no,
                  "updated_at": now}})
    await audit(actor, AUDIT_LETTER_REISSUED, ENTITY_LETTER, new_no,
               f"supersedes {letter_no}: {reason}", company_id)
    return await get_letter(actor, company_id, new_no)
