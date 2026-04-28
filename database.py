import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()  # local dev only — HF uses secrets directly

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")

supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
