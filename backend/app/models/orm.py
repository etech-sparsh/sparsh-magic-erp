from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class AuditItemSchema(BaseModel):
    sno: int
    checkpoint: str
    max_marks: float = 5.0
    response: Optional[str] = "No" # Yes/No
    obtained_marks: float = 0.0
    remarks: Optional[str] = ""

class TeamEngagementItemSchema(BaseModel):
    sno: int
    question: str
    min_marks: float = 0.0
    review: Optional[str] = ""

class BudgetAdherenceItemSchema(BaseModel):
    sno: int
    particulars: str
    head: str
    subhead: str
    rate: float = 0.0
    target: float = 0.0
    actual: float = 0.0
    gap: float = 0.0
    raised_by: Optional[str] = ""
    raised_to: Optional[str] = ""
    reason: Optional[str] = ""

class SubsectionSchema(BaseModel):
    id: str
    name: str
    weightage: float
    target: float
    achievement: float
    assignedUsers: List[str] = []
    isPercentage: Optional[bool] = False
    frequency: Optional[str] = "none" # none, monthly, quarterly, six_monthly
    dayOfMonth: Optional[int] = 1
    hasAudit: Optional[bool] = False
    auditName: Optional[str] = ""
    unitName: Optional[str] = ""
    remarks: Optional[str] = ""
    googleSheetLink: Optional[str] = ""
    googleFormLink: Optional[str] = ""
    surveyLevel: Optional[str] = "public" # public, anonymous
    surveyDoerName: Optional[str] = ""
    surveyDoerEmail: Optional[str] = ""
    auditChecklist: List[AuditItemSchema] = []
    teamEngagementChecklist: Optional[List[TeamEngagementItemSchema]] = []
    budgetAdherenceChecklist: Optional[List[BudgetAdherenceItemSchema]] = []

class ParameterSchema(BaseModel):
    id: str
    name: str
    weightage: float
    isReverse: Optional[bool] = False
    assignedUsers: List[str] = []
    subsections: List[SubsectionSchema]

class ORMCreateRequest(BaseModel):
    company_id: str
    parameters: List[ParameterSchema]
    total_weightage: float
    total_score: float
    period: Optional[str] = None  # "YYYY-MM"; defaults to current month server-side

class ORMResponse(BaseModel):
    id: str = Field(alias="_id")
    company_id: str
    parameters: List[ParameterSchema]
    total_weightage: float
    total_score: float
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True
