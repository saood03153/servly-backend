from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from models import TaskRequest, AcceptTaskRequest, ProviderStatusUpdate, AgentChatRequest
from agent import run_agentic_loop
from langgraph_agent import run_agent
from gemini_utils import parse_intent
from database import supabase_client

app = FastAPI(title="Servly AI Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "Servly AI Backend"}


@app.post("/api/tasks/create-agentic")
async def create_agentic_task(
    request: TaskRequest, background_tasks: BackgroundTasks
):
    """Create a task and start the autonomous agent loop."""
    # Parse intent with Gemini
    intent = await parse_intent(request.problem_description)
    category = intent.get("category", request.category)

    # 1. Create task record in Supabase
    task = supabase_client.table("tasks").insert(
        {
            "seeker_id": request.seeker_id,
            "problem_description": request.problem_description,
            "category": category,
            "urgency": intent.get("urgency"),
            "summary": intent.get("summary"),
            "status": "searching",
            "seeker_location": f"SRID=4326;POINT({request.lng} {request.lat})",
            "lat": request.lat,
            "lng": request.lng,
        }
    ).execute()

    task_id = task.data[0]["id"]

    # 2. Kick off agent in background (non-blocking)
    background_tasks.add_task(
        run_agentic_loop,
        task_id=task_id,
        lat=request.lat,
        lng=request.lng,
        category=category,
        problem=request.problem_description,
    )

    return {"task_id": task_id, "status": "agent_started", "intent": intent}


@app.post("/api/tasks/{task_id}/accept")
async def accept_task(task_id: str, body: AcceptTaskRequest):
    """Provider accepts a task."""
    supabase_client.table("tasks").update(
        {"status": "accepted", "provider_id": body.provider_id}
    ).eq("id", task_id).execute()
    return {"status": "accepted"}


@app.post("/api/tasks/{task_id}/complete")
async def complete_task(task_id: str):
    """Mark task as completed."""
    from datetime import datetime

    supabase_client.table("tasks").update(
        {"status": "completed", "completed_at": datetime.utcnow().isoformat()}
    ).eq("id", task_id).execute()
    return {"status": "completed"}


@app.get("/api/providers/nearby")
async def get_nearby_providers(
    lat: float, lng: float, category: str = None, radius: float = 5.0
):
    result = supabase_client.rpc(
        "find_nearby_providers",
        {"lat": lat, "lng": lng, "radius_km": radius, "skill_filter": category},
    ).execute()
    return result.data


@app.patch("/api/providers/{provider_id}/status")
async def update_provider_status(provider_id: str, body: ProviderStatusUpdate):
    """Provider toggles online/offline/busy."""
    supabase_client.table("profiles").update({"status": body.status}).eq(
        "id", provider_id
    ).execute()
    return {"status": body.status}


# ─── LangGraph Agent Chat ────────────────────────────────────────────────────────

@app.post("/api/agent/chat")
async def agent_chat(request: AgentChatRequest):
    """
    Conversational LangGraph agent endpoint.
    Controls the entire Servly platform via natural language:
    - Account creation & profile setup
    - Service search & task creation
    - Provider notifications & job acceptance
    - Task completion & provider rating

    Body:
        message: User's natural language input
        user_id: (optional) authenticated Supabase user ID
        conversation_history: (optional) prior turns for multi-turn context
    """
    history = [
        {"role": m.role, "content": m.content}
        for m in (request.conversation_history or [])
    ]
    result = await run_agent(
        user_message=request.message,
        conversation_history=history,
        user_id=request.user_id,
    )
    return {
        "response": result["response"],
        "history": result["history"],
    }
