from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class SystemSettings(BaseModel):
    setting_name: str = "backdate_control"
    allow_backdate: bool = False
    exception_users: List[str] = [] # List of email addresses
    updated_by: Optional[str] = None # SuperAdmin ID
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class SystemSettingsUpdate(BaseModel):
    allow_backdate: Optional[bool] = None
    exception_users: Optional[List[str]] = None


# ─────────────────────────────────────────────────────────────
# Where this deployment is reachable in a browser.
#
# Mailed links (the per-person TPMS form links above all) must be ABSOLUTE — an email has no
# base document, so a relative href resolves against the mail client's own origin. The base
# used to come only from the FRONTEND_URL environment variable, which meant a server started
# without it mailed http://localhost:5173 links that open on nobody's machine but the one that
# sent them. Holding it as a setting lets it be corrected from the UI, without a redeploy.
# ─────────────────────────────────────────────────────────────
class AppUrlSettings(BaseModel):
    setting_name: str = "app_url"
    frontend_url: str = ""
    updated_by: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AppUrlUpdate(BaseModel):
    frontend_url: str
