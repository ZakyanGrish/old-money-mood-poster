"""Loads .env and accounts.json, resolves an account to its IDs and access token."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Optional[Path] = None) -> None:
    """Minimal .env loader (KEY=VALUE per line). No dependency on python-dotenv."""
    path = path or (ROOT / ".env")
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Real environment variables win over .env
        os.environ.setdefault(key, value)


class Account:
    def __init__(self, name: str, ig_user_id: str, fb_page_id: Optional[str], access_token: str):
        self.name = name
        self.ig_user_id = ig_user_id
        self.fb_page_id = fb_page_id
        self.access_token = access_token


def _accounts_file() -> Path:
    p = ROOT / "accounts.json"
    if not p.exists():
        raise SystemExit(
            "accounts.json not found. Copy accounts.example.json to accounts.json and fill it in "
            "(run: python scripts/meta_get_ids.py to discover your IDs)."
        )
    return p


def load_accounts() -> Dict[str, dict]:
    return json.loads(_accounts_file().read_text())


def get_account(name: str) -> Account:
    load_env()
    accounts = load_accounts()
    if name not in accounts:
        raise SystemExit(
            "Unknown account '%s'. Known: %s" % (name, ", ".join(sorted(accounts)) or "(none)")
        )
    cfg = accounts[name]
    token_env = cfg.get("token_env") or "META_ACCESS_TOKEN"
    token = os.environ.get(token_env, "")
    if not token:
        raise SystemExit("No access token: env var %s is empty (check your .env)." % token_env)
    ig_user_id = str(cfg.get("ig_user_id") or "").strip()
    if not ig_user_id:
        raise SystemExit("Account '%s' has no ig_user_id in accounts.json." % name)
    fb_page_id = cfg.get("fb_page_id")
    return Account(name, ig_user_id, str(fb_page_id) if fb_page_id else None, token)
