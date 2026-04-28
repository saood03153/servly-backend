from pydantic import BaseModel
from typing import Optional, List


class TaskRequest(BaseModel):
    seeker_id: str
    problem_description: str
    category: str
    lat: float
    lng: float


class AcceptTaskRequest(BaseModel):
    provider_id: str


class ProviderStatusUpdate(BaseModel):
    status: str  # online | offline | busy


class AgentChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class AgentChatRequest(BaseModel):
    message: str
    user_id: Optional[str] = None
    conversation_history: Optional[List[AgentChatMessage]] = []
