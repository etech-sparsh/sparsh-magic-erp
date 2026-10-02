"""Module configuration for the AI Assistant.

Values here are intentionally static for Phase 0. Secrets (e.g. OpenAI key) are
read from app.config.settings when the LLM layer is wired in Phase 1.
"""


class AssistantConfig:
    # Feature flag — lets ops disable the assistant without removing the router.
    ENABLED: bool = True

    # Model tiers (used from Phase 1 onward; no calls are made in Phase 0).
    PRIMARY_MODEL: str = "gpt-4o"        # reasoning + final answers
    UTILITY_MODEL: str = "gpt-4o-mini"   # query rewriting, summaries, titles

    # Agent loop guards.
    MAX_TOOL_ITERATIONS: int = 6         # safety cap on tool-calling rounds
    #   (6 lets a multi-entity question — e.g. "compare two batches and a company" —
    #   chain several tool calls without tripping the "couldn't finish" fallback.)
    TOOL_TIMEOUT_SECONDS: float = 8.0    # per-tool execution timeout (cross-cutting)
    LLM_TEMPERATURE: float = 0.3

    # Conversation memory / windowing (Phase 2).
    MAX_WINDOW_MESSAGES: int = 10        # recent user/assistant messages sent to the LLM
    SUMMARY_TRIGGER: int = 14            # message_count above which older turns are summarized
    CONVERSATION_LIST_LIMIT: int = 50

    # ── Phase 4: production hardening ─────────────────────────────────────
    # Feature flags.
    STREAMING_ENABLED: bool = True
    RAG_ENABLED: bool = True
    ANALYTICS_ENABLED: bool = True
    GUARDRAILS_ENABLED: bool = True

    # Rollout controls.
    ENABLED_ROLES: list = []             # empty = all roles; else raw role strings
    ROLLOUT_MODE: str = "all"            # all | allowlist | percentage
    ROLLOUT_ALLOWLIST: list = []         # user_ids or emails
    ROLLOUT_PERCENT: int = 100           # used when ROLLOUT_MODE == "percentage"

    # Rate limiting (per user).
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_MAX: int = 30             # requests...
    RATE_LIMIT_WINDOW: float = 60.0      # ...per this many seconds

    # Caching TTLs (seconds).
    CACHE_METADATA_TTL: float = 300.0    # accessible projects, profile-ish metadata
    CACHE_ANALYTICS_TTL: float = 60.0    # analytics results
    CACHE_KNOWLEDGE_TTL: float = 120.0   # knowledge retrieval results

    # Cost reporting.
    COST_REPORTING_ENABLED: bool = True
    COST_COLLECTION: str = "assistant_cost"
    METRICS_COLLECTION: str = "assistant_metrics"

    # Persistence.
    CONVERSATION_COLLECTION: str = "assistant_conversations"

    # ── RAG: semantic (vector) retrieval ──────────────────────────────────
    # Master switch for vector search. When True, retrieval tools embed the
    # query and run Atlas $vectorSearch first, then FALL BACK to keyword search
    # on any miss/error/missing-embedding — so turning this off (or a missing
    # index / API key) silently reverts to the existing keyword behaviour.
    RAG_VECTOR_ENABLED: bool = True
    EMBED_MODEL: str = "text-embedding-3-small"
    EMBED_DIMS: int = 1536
    EMBED_MAX_CHARS: int = 8000          # ~2k tokens; truncate before embedding
    EMBED_BATCH: int = 100              # texts per embeddings API call
    RAG_NUM_CANDIDATES_FACTOR: int = 20  # ANN candidate pool = factor * limit
    # Minimum cosine score for a vector hit to "win" over keyword search. Floors
    # out weak nearest-neighbour noise so that (a) during a partial backfill a
    # garbage hit can't suppress keyword search of still-un-embedded docs, and
    # (b) genuinely-unrelated queries fall through to keyword instead of
    # returning irrelevant chunks. 0.30 keeps real matches (~0.4+) comfortably.
    RAG_MIN_SCORE: float = 0.30
    # Atlas Search vector index names (created by scripts/setup_vector_indexes.py).
    KNOWLEDGE_VECTOR_INDEX: str = "kb_vector_index"
    ATTACHMENT_VECTOR_INDEX: str = "attach_vector_index"
    MEDIA_VECTOR_INDEX: str = "media_vector_index"
    # Per-file content chunks for the Media Library (vector-searchable).
    MEDIA_CHUNK_COLLECTION: str = "media_chunks"

    # ── Multi-modal attachments ───────────────────────────────────────────
    # Master switch for the file-upload subsystem (additive; safe to disable).
    ATTACHMENTS_ENABLED: bool = True
    ATTACHMENT_COLLECTION: str = "assistant_attachments"
    # Per-conversation retrieval chunks backing search_uploaded_files.
    ATTACHMENT_CHUNK_COLLECTION: str = "assistant_attachment_chunks"

    # Storage backend: "local" (dev) or "s3" (prod). See files/storage.py.
    STORAGE_PROVIDER: str = "s3"

    # Upload limits (configurable; enforced server-side in files/service.py).
    MAX_FILES_PER_MESSAGE: int = 25
    MAX_FILE_SIZE_MB: int = 100
    MAX_REQUEST_SIZE_MB: int = 500

    # Default instruction used when a turn carries attachments but no text
    # message (e.g. the user uploads a file and hits send with an empty box).
    # Without this the empty message is run through the query rewriter, which
    # invents a spurious question ("what is the latest message?") and derails
    # the answer instead of describing the file.
    DEFAULT_ATTACHMENT_PROMPT: str = (
        "Please provide a clear, concise summary of the attached file(s), "
        "highlighting the key points."
    )

    # Context-injection caps so large files never blow the model context window.
    MAX_EXTRACTED_CHARS_PER_FILE: int = 24000
    MAX_TOTAL_ATTACHMENT_CHARS: int = 60000
    MAX_IMAGES_PER_TURN: int = 8

    # Safe ZIP extraction guards (zip-bomb / zip-slip protection).
    ZIP_MAX_ENTRIES: int = 200
    ZIP_MAX_TOTAL_BYTES: int = 200 * 1024 * 1024  # 200 MB uncompressed

    # Allowed upload extensions (lower-case, no dot). Mirrors the product spec.
    ALLOWED_EXTENSIONS: set = {
        # documents
        "pdf", "doc", "docx", "txt", "md", "rtf",
        # spreadsheets
        "xls", "xlsx", "csv",
        # presentations
        "ppt", "pptx",
        # images
        "jpg", "jpeg", "png", "webp", "gif",
        # audio
        "mp3", "wav", "aac", "ogg", "m4a", "flac",
        # video
        "mp4", "mov", "avi", "mkv", "webm",
        # development / code
        "js", "jsx", "ts", "tsx", "py", "java", "php", "cpp", "c", "h",
        "cs", "go", "rb", "rs", "kt", "swift", "sql", "sh",
        "json", "xml", "yaml", "yml", "html", "css",
        # archives
        "zip", "rar", "7z",
    }
    # Always-blocked extensions (executables / installers / scripts), even if
    # they slip past the allowlist via a double extension.
    BLOCKED_EXTENSIONS: set = {
        "exe", "dll", "bat", "cmd", "com", "scr", "msi", "msix",
        "vbs", "ps1", "jar", "app", "deb", "rpm", "bin", "so", "dylib",
    }

    # Response sizing defaults (response_formatter refines per query, Phase 2/3).
    SHORT_ANSWER_MAX_TOKENS: int = 200
    LONG_ANSWER_MAX_TOKENS: int = 1200


config = AssistantConfig()
