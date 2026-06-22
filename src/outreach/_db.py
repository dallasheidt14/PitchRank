"""Shared Supabase client + env loading for the outreach pipeline modules.

Mirrors the script convention (inline ``load_dotenv(.env.local)`` then ``.env``
from the repo root, then ``create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)``).
The service-role key is required: outreach_targets is RLS service-role-only.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from supabase import create_client

TABLE = "outreach_targets"


def _load_repo_env():
    repo_root = Path(__file__).resolve().parents[2]  # src/outreach/_db.py -> repo root
    load_dotenv(repo_root / ".env.local")
    load_dotenv(repo_root / ".env")


def get_client():
    _load_repo_env()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(url, key)
