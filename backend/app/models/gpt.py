from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class GptProjectBase(BaseModel):
    title: str
    description: Optional[str] = None
    instruction: str
    conversation_starters: List[str] = []
    knowledge_files: List[dict] = [] # List of {id, name, type, url}

class GptProjectCreate(GptProjectBase):
    pass

class GptProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    instruction: Optional[str] = None
    conversation_starters: Optional[List[str]] = None

class GptProjectResponse(GptProjectBase):
    id: str = Field(alias="_id")
    created_by: str
    created_at: datetime

    class Config:
        populate_by_name = True

class GptChatMessage(BaseModel):
    role: str # user | assistant
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class GptConversation(BaseModel):
    project_id: str
    user_id: str
    messages: List[GptChatMessage] = []
    updated_at: datetime = Field(default_factory=datetime.utcnow)
