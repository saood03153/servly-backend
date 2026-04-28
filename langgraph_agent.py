"""
Servly AI — LangGraph Autonomous Agent
Controls the entire platform: account creation → profile → service finding → task lifecycle
"""

import os
import asyncio
from typing import Annotated, TypedDict, Literal
from datetime import datetime

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    SystemMessage,
    BaseMessage,
)
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from database import supabase_client
from firebase_utils import send_fcm_notification


# ─── Agent State ────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str | None
    task_id: str | None


# ─── Tools ──────────────────────────────────────────────────────────────────────

@tool
def create_user_account(phone: str, name: str, role: str) -> dict:
    """Create a new Servly user account or log in an existing one.
    role must be exactly 'seeker' (needs service) or 'provider' (offers service).
    Returns user profile with id, name, role."""
    try:
        existing = (
            supabase_client.table("profiles")
            .select("id, name, role, status, rating, total_jobs")
            .eq("phone", phone)
            .execute()
        )
        if existing.data:
            return {"success": True, "action": "login", "user": existing.data[0]}

        result = (
            supabase_client.table("profiles")
            .insert(
                {
                    "phone": phone,
                    "name": name,
                    "role": role,
                    "status": "offline",
                    "rating": 0.0,
                    "total_jobs": 0,
                    "created_at": datetime.utcnow().isoformat(),
                }
            )
            .execute()
        )
        return {"success": True, "action": "created", "user": result.data[0]}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def get_user_profile(user_id: str) -> dict:
    """Get complete profile for a user by their user_id.
    Returns name, role, skills, bio, rating, total_jobs, status."""
    try:
        result = (
            supabase_client.table("profiles")
            .select("*")
            .eq("id", user_id)
            .single()
            .execute()
        )
        return {"success": True, "profile": result.data}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def update_user_profile(
    user_id: str,
    name: str = None,
    skills: list = None,
    bio: str = None,
    avatar_url: str = None,
) -> dict:
    """Update a user's profile. Provide only fields to change.
    skills is a list like ['Plumbing', 'Electrical']. bio is a short description."""
    try:
        updates = {}
        if name:
            updates["name"] = name
        if skills:
            updates["skills"] = skills
        if bio:
            updates["bio"] = bio
        if avatar_url:
            updates["avatar_url"] = avatar_url

        supabase_client.table("profiles").update(updates).eq("id", user_id).execute()
        return {"success": True, "updated_fields": list(updates.keys())}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def set_provider_status(provider_id: str, status: str) -> dict:
    """Toggle provider availability. status must be 'online', 'offline', or 'busy'.
    Providers must be online to receive job requests."""
    try:
        supabase_client.table("profiles").update({"status": status}).eq(
            "id", provider_id
        ).execute()
        return {"success": True, "provider_id": provider_id, "new_status": status}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def search_nearby_providers(
    lat: float, lng: float, category: str = None, radius_km: float = 5.0
) -> dict:
    """Search for available service providers near a location.
    lat/lng are GPS coordinates. radius_km defaults to 5km.
    category options: Automobile, Bike Repair, Education, Home Services, Electronics, Other.
    Leave category as None to search all categories."""
    try:
        result = supabase_client.rpc(
            "find_nearby_providers",
            {
                "lat": lat,
                "lng": lng,
                "radius_km": radius_km,
                "skill_filter": category,
                "max_results": 10,
            },
        ).execute()

        providers = result.data or []
        return {
            "success": True,
            "count": len(providers),
            "providers": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "skills": p.get("skills", []),
                    "rating": p.get("rating", 0),
                    "total_jobs": p.get("total_jobs", 0),
                    "status": p.get("status"),
                    "distance_km": round(p.get("distance_km", 0), 2),
                    "fcm_token": p.get("fcm_token"),
                }
                for p in providers
            ],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def create_service_request(
    seeker_id: str,
    problem_description: str,
    category: str,
    lat: float,
    lng: float,
    urgency: str = "medium",
    summary: str = "",
) -> dict:
    """Create a new service request task on behalf of a seeker.
    urgency: 'low', 'medium', or 'high'.
    Returns task_id which can be used for notifications and status tracking."""
    try:
        result = (
            supabase_client.table("tasks")
            .insert(
                {
                    "seeker_id": seeker_id,
                    "problem_description": problem_description,
                    "category": category,
                    "urgency": urgency,
                    "summary": summary,
                    "status": "searching",
                    "lat": lat,
                    "lng": lng,
                    "seeker_location": f"SRID=4326;POINT({lng} {lat})",
                    "created_at": datetime.utcnow().isoformat(),
                }
            )
            .execute()
        )
        task_id = result.data[0]["id"]
        return {"success": True, "task_id": task_id, "status": "searching"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def notify_provider(
    fcm_token: str, task_id: str, problem_summary: str, provider_name: str
) -> dict:
    """Send a push notification to a provider about a new job.
    fcm_token comes from the provider's profile. problem_summary should be brief (< 80 chars)."""
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            send_fcm_notification(
                token=fcm_token,
                title="New Job Request — Servly AI",
                body=f"Problem: {problem_summary[:80]}",
                data={"task_id": task_id, "type": "job_request"},
            )
        )
        loop.close()
        return {"success": True, "notified_provider": provider_name}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def accept_service_request(task_id: str, provider_id: str) -> dict:
    """Mark a task as accepted by a provider.
    Call this when a provider agrees to take a job."""
    try:
        supabase_client.table("tasks").update(
            {"status": "accepted", "provider_id": provider_id}
        ).eq("id", task_id).execute()
        return {"success": True, "task_id": task_id, "status": "accepted"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def complete_service_request(task_id: str) -> dict:
    """Mark a task as completed. Call when the provider finishes the job."""
    try:
        supabase_client.table("tasks").update(
            {
                "status": "completed",
                "completed_at": datetime.utcnow().isoformat(),
            }
        ).eq("id", task_id).execute()
        return {"success": True, "task_id": task_id, "status": "completed"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def get_task_status(task_id: str) -> dict:
    """Get current status and full details of a task by task_id.
    Returns status, provider info, seeker info, and timestamps."""
    try:
        result = (
            supabase_client.table("tasks")
            .select("*")
            .eq("id", task_id)
            .single()
            .execute()
        )
        task = result.data
        # Fetch provider name if assigned
        if task.get("provider_id"):
            p = (
                supabase_client.table("profiles")
                .select("name, rating, skills")
                .eq("id", task["provider_id"])
                .single()
                .execute()
            )
            task["provider"] = p.data
        return {"success": True, "task": task}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def get_my_jobs(user_id: str, role: str) -> dict:
    """Get job history for a user.
    role='seeker' returns jobs they posted.
    role='provider' returns jobs they accepted/completed.
    Returns list of tasks sorted by newest first."""
    try:
        if role == "seeker":
            result = (
                supabase_client.table("tasks")
                .select("*")
                .eq("seeker_id", user_id)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
        else:
            result = (
                supabase_client.table("tasks")
                .select("*")
                .eq("provider_id", user_id)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
        return {
            "success": True,
            "count": len(result.data),
            "jobs": result.data,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def rate_provider(
    task_id: str, provider_id: str, rating: float, review: str = ""
) -> dict:
    """Rate a provider after job completion. rating must be between 1.0 and 5.0.
    This updates both the task record and the provider's average rating."""
    try:
        if not (1.0 <= rating <= 5.0):
            return {"success": False, "error": "Rating must be between 1.0 and 5.0"}

        supabase_client.table("tasks").update(
            {"rating": rating, "review": review}
        ).eq("id", task_id).execute()

        # Recalculate provider's average rating
        jobs = (
            supabase_client.table("tasks")
            .select("rating")
            .eq("provider_id", provider_id)
            .not_.is_("rating", "null")
            .execute()
        )
        ratings = [j["rating"] for j in jobs.data if j.get("rating")]
        if ratings:
            avg = round(sum(ratings) / len(ratings), 1)
            supabase_client.table("profiles").update(
                {"rating": avg, "total_jobs": len(ratings)}
            ).eq("id", provider_id).execute()

        return {
            "success": True,
            "rating_given": rating,
            "provider_new_avg": avg if ratings else rating,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def cancel_task(task_id: str, reason: str = "") -> dict:
    """Cancel an active task. Use when a seeker no longer needs the service."""
    try:
        supabase_client.table("tasks").update({"status": "cancelled"}).eq(
            "id", task_id
        ).execute()
        return {"success": True, "task_id": task_id, "status": "cancelled"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─── All Tools ──────────────────────────────────────────────────────────────────

ALL_TOOLS = [
    create_user_account,
    get_user_profile,
    update_user_profile,
    set_provider_status,
    search_nearby_providers,
    create_service_request,
    notify_provider,
    accept_service_request,
    complete_service_request,
    get_task_status,
    get_my_jobs,
    rate_provider,
    cancel_task,
]

# ─── System Prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Servly AI — an intelligent autonomous agent that controls the entire Servly service platform.

You have full control over:
1. ACCOUNTS: Create seeker accounts (need help) and provider accounts (offer services)
2. PROFILES: Setup and update name, skills, bio, avatar
3. SERVICE SEARCH: Find nearby providers by GPS + category
4. TASK LIFECYCLE: Create requests → notify providers → accept → complete
5. RATINGS: Rate providers after job completion
6. STATUS MANAGEMENT: Toggle providers online/offline/busy
7. JOB HISTORY: View past jobs for seekers and providers

WORKFLOW for seekers:
1. Create account (phone, name, role='seeker')
2. Search nearby providers for their problem category
3. Create service request
4. Notify found providers with FCM
5. Track task until accepted/completed
6. Rate provider when done

WORKFLOW for providers:
1. Create account (phone, name, role='provider')  
2. Update profile with skills
3. Set status to 'online' to receive jobs
4. Accept incoming job requests
5. Complete jobs when done

RULES:
- Always use the tools — never make up data
- When someone describes a problem, immediately identify the category and search for providers
- Be concise and action-oriented
- If a tool fails, explain the error clearly
- Never guess user IDs or task IDs — always get them from tool results
"""

# ─── LangGraph Build ────────────────────────────────────────────────────────────

def build_servly_graph():
    llm = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        google_api_key=os.environ["GEMINI_API_KEY"],
        temperature=0.1,
    )
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    def agent_node(state: AgentState):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: AgentState) -> Literal["tools", "end"]:
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return "end"

    tool_node = ToolNode(ALL_TOOLS)

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent", should_continue, {"tools": "tools", "end": END}
    )
    graph.add_edge("tools", "agent")

    return graph.compile()


# Singleton compiled graph
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_servly_graph()
    return _graph


# ─── Public Entry Point ─────────────────────────────────────────────────────────

async def run_agent(
    user_message: str,
    conversation_history: list[dict] = None,
    user_id: str = None,
) -> dict:
    """
    Run the Servly LangGraph agent.

    Args:
        user_message: The user's latest message
        conversation_history: Prior turns as [{"role": "user"|"assistant", "content": "..."}]
        user_id: Optional — the authenticated user's Supabase ID

    Returns:
        {"response": str, "history": list[dict]}
    """
    graph = get_graph()

    messages: list[BaseMessage] = []
    if conversation_history:
        for msg in conversation_history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))

    messages.append(HumanMessage(content=user_message))

    state = {
        "messages": messages,
        "user_id": user_id,
        "task_id": None,
    }

    result = await graph.ainvoke(state)

    last = result["messages"][-1]
    history = []
    for m in result["messages"]:
        if isinstance(m, HumanMessage) and m.content:
            history.append({"role": "user", "content": m.content})
        elif isinstance(m, AIMessage) and m.content:
            history.append({"role": "assistant", "content": m.content})

    return {
        "response": last.content if hasattr(last, "content") else "",
        "history": history,
    }
