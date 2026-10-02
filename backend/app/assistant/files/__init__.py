"""Multi-modal attachment subsystem for the assistant.

Adds file upload → storage → extraction → context-injection on top of the
text-only chat. Everything here is additive and gated by
`config.ATTACHMENTS_ENABLED`; the existing chat path is untouched when no
attachments are present.

Modules:
  storage          — local/S3 storage abstraction (provider-selected)
  extractor        — text/transcript/image extraction across file types
  attachment_store — Mongo persistence (owner-scoped) for assistant_attachments
  service          — validation, upload orchestration, background processing
"""
