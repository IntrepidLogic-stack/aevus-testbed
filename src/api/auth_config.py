"""
Aevus API -- Auth Config Endpoint
Serves public Supabase config to the frontend (URL + anon key only).
"""

from fastapi import APIRouter

from src.config import settings

auth_config_router = APIRouter(tags=["auth"])


@auth_config_router.get("/auth/config")
async def get_auth_config():
    """Return public Supabase config for the login page.
    Only returns the URL and anon key (both are public values)."""
    return {
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": settings.supabase_anon_key,
    }
