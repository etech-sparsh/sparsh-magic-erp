"""Admin-domain tools.

Superadmin (SA only) tools — org-wide and entity-level visibility:
  * Tier 1 (org_tools): list_batches, list_companies, get_platform_stats, list_users
  * Tier 2 (drilldown_tools): get_company_overview, get_batch_details, get_user_activity
  * Media library (media_tools): list_media_library
  * Calendar (calendar_tools): list_sessions

All submodules enforce the SA-only restriction and strip PII. Importing them
here runs the @tool decorators so the tools self-register when
registry.register_all() imports this package.
"""
from app.assistant.tools.admin import (  # noqa: F401
    calendar_tools,
    drilldown_tools,
    media_tools,
    org_tools,
)
