from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# Holiday master records (collection: "holidays"). holiday_date is stored as an ISO date
# string ("YYYY-MM-DD") to match how the rest of the app handles calendar dates and to keep
# month/year filtering and upcoming/past comparisons simple on both ends.
class HolidayBase(BaseModel):
    holiday_name: str
    holiday_date: str  # ISO "YYYY-MM-DD"
    description: Optional[str] = None
    holiday_type: Optional[str] = "Company"  # National | Festival | Company | Optional
    status: Optional[str] = "active"  # active | inactive


class HolidayCreate(HolidayBase):
    pass


class HolidayUpdate(BaseModel):
    holiday_name: Optional[str] = None
    holiday_date: Optional[str] = None
    description: Optional[str] = None
    holiday_type: Optional[str] = None
    status: Optional[str] = None


class HolidayResponse(HolidayBase):
    id: str
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
