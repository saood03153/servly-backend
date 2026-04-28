import asyncio
from datetime import datetime
from database import supabase_client
from firebase_utils import send_fcm_notification
from gemini_utils import parse_intent

TIMEOUT_SECONDS = 120  # 2-minute provider window


async def log_agent(task_id: str, message: str, log_type: str = "info"):
    """Write a log entry — Flutter subscribes to these in real-time."""
    supabase_client.table("agent_logs").insert(
        {
            "task_id": task_id,
            "log_message": message,
            "log_type": log_type,
            "timestamp": datetime.utcnow().isoformat(),
        }
    ).execute()


async def run_agentic_loop(
    task_id: str, lat: float, lng: float, category: str, problem: str
):
    """
    The core autonomous loop:
    1. Find up to 5 nearest online providers
    2. Ping each with a push notification
    3. Wait 120 seconds for acceptance
    4. Failover to next provider if no response
    """
    await log_agent(task_id, f"Analyzing your problem: '{problem}'...", "info")
    await asyncio.sleep(1.5)
    await log_agent(task_id, f"Category identified: {category}", "success")

    # Fetch nearest providers via PostGIS
    providers_result = supabase_client.rpc(
        "find_nearby_providers",
        {
            "lat": lat,
            "lng": lng,
            "radius_km": 5.0,
            "skill_filter": category,
            "max_results": 5,
        },
    ).execute()
    providers = providers_result.data

    if not providers:
        await log_agent(task_id, "No providers found nearby. Try again later.", "error")
        supabase_client.table("tasks").update({"status": "failed"}).eq(
            "id", task_id
        ).execute()
        return

    await log_agent(
        task_id, f"Found {len(providers)} nearby expert(s). Starting contact...", "info"
    )

    for i, provider in enumerate(providers):
        name = provider["name"]
        fcm = provider.get("fcm_token")

        await log_agent(task_id, f"Pinging {name} (Expert #{i + 1})...", "ping")

        # Send Firebase push notification
        if fcm:
            await send_fcm_notification(
                token=fcm,
                title="New Job Request — Servly AI",
                body=f"Problem: {problem[:80]}...",
                data={"task_id": task_id, "type": "job_request"},
            )

        await log_agent(
            task_id,
            f"Waiting for {name}'s response (up to 120 seconds)...",
            "info",
        )

        # Poll every 5 seconds for 120 seconds
        accepted = False
        for elapsed in range(0, TIMEOUT_SECONDS, 5):
            await asyncio.sleep(5)
            task_status = (
                supabase_client.table("tasks")
                .select("status,provider_id")
                .eq("id", task_id)
                .single()
                .execute()
            )

            if task_status.data["status"] == "accepted":
                accepted = True
                break

            remaining = TIMEOUT_SECONDS - elapsed - 5
            if remaining > 0 and elapsed % 30 == 0:
                await log_agent(
                    task_id,
                    f"Still waiting for {name}... ({remaining}s remaining)",
                    "info",
                )

        if accepted:
            provider_data = (
                supabase_client.table("profiles")
                .select("*")
                .eq("id", task_status.data["provider_id"])
                .single()
                .execute()
            )
            await log_agent(
                task_id,
                f"Match found! {provider_data.data['name']} accepted your request!",
                "success",
            )
            return  # SUCCESS — exit loop

        # Timeout — try next provider
        if i < len(providers) - 1:
            await log_agent(
                task_id, f"{name} did not respond. Trying next expert...", "warning"
            )
        else:
            await log_agent(
                task_id,
                "All experts contacted. No match found. Please try again.",
                "error",
            )
            supabase_client.table("tasks").update({"status": "failed"}).eq(
                "id", task_id
            ).execute()
