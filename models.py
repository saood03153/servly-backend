from pydantic import BaseModel
from typing import Optional


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
