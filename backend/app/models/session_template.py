from pydantic import BaseModel, Field
from typing import Optional, List, Union
from datetime import datetime

class TaskTemplate(BaseModel):
    title: str
    points: int = 0

class AssessmentQuestion(BaseModel):
    question_text: str
    type: str = "MCQ" # MCQ, Descriptive
    options: Optional[List[str]] = None # Only for MCQ
    correct_option_index: Optional[int] = None # Only for MCQ
    expected_answer: Optional[str] = None # Only for Descriptive
    instruction: Optional[str] = None # Only for Descriptive
    marks: int = 1 # Points for this question

class AssessmentTemplate(BaseModel):
    title: str
    passing_score: int = 70
    shuffle_questions: bool = False
    questions_to_show: Optional[int] = None # Limit if shuffled
    questions: List[AssessmentQuestion] = []

class SessionTemplateBase(BaseModel):
    title: str
    topic: str
    description: Optional[str] = None
    tasks: List[TaskTemplate] = []
    assessments: List[AssessmentTemplate] = []

class SessionTemplateCreate(BaseModel):
    title: str
    topic: str
    description: Optional[str] = None

class SessionTemplateUpdate(BaseModel):
    title: Optional[str] = None
    topic: Optional[str] = None
    description: Optional[str] = None
    tasks: Optional[List[TaskTemplate]] = None
    assessments: Optional[List[AssessmentTemplate]] = None

class SessionTemplateResponse(SessionTemplateBase):
    id: str = Field(alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
