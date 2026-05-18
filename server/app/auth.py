"""OpenAI OAuth authentication support.

Reads and manages OAuth tokens from opencode's auth.json.
Token refresh is handled automatically when expired.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agno.utils.log import log_debug, log_error, log_warning

OPENCODE_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
TOKEN_REFRESH_URL = "https://auth.openai.com/oauth/token"
TOKEN_REFRESH_BUFFER_MS = 5 * 60 * 1000


def get_auth_path() -> Path | None:
    """Return the path to auth.json.

    Search order:
    1. NOWORK_AUTH_PATH environment variable
    2. opencode's default path: ~/.local/share/opencode/auth.json

    Returns None if neither exists.
    """
    import os

    env_path = os.environ.get("NOWORK_AUTH_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    opencode_path = Path.home() / ".local" / "share" / "opencode" / "auth.json"
    if opencode_path.exists():
        return opencode_path

    return None


def load_auth() -> dict[str, Any]:
    """Load auth.json content.

    Returns empty dict if file doesn't exist.
    """
    auth_path = get_auth_path()
    if not auth_path:
        return {}
    try:
        with open(auth_path, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        log_error(f"Failed to load auth.json: {e}")
        return {}


def save_auth(data: dict[str, Any]) -> bool:
    """Save data to opencode's auth.json.

    We always write to opencode's path to keep tokens in sync.
    Returns True on success.
    """
    auth_path = Path.home() / ".local" / "share" / "opencode" / "auth.json"
    try:
        auth_path.parent.mkdir(parents=True, exist_ok=True)
        with open(auth_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        log_error(f"Failed to save auth.json: {e}")
        return False


def get_oauth_token(provider_id: str = "openai") -> dict[str, Any] | None:
    """Get OAuth token data for a provider.

    Returns the OAuth entry from auth.json, or None if not found.
    """
    auth = load_auth()
    provider_data = auth.get(provider_id)
    if not provider_data:
        return None
    if provider_data.get("type") != "oauth":
        return None
    return provider_data


def _refresh_oauth_token(refresh_token: str) -> dict[str, Any] | None:
    """Refresh OAuth token using OpenAI's token endpoint.

    Returns new token data on success, None on failure.
    """
    import httpx

    try:
        resp = httpx.post(
            TOKEN_REFRESH_URL,
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": OPENCODE_CLIENT_ID,
            },
            timeout=15.0,
        )

        if resp.status_code != 200:
            log_error(f"Token refresh failed: {resp.status_code} - {resp.text[:200]}")
            return None

        data = resp.json()
        return {
            "access": data.get("access_token"),
            "refresh": data.get("refresh_token", refresh_token),
            "expires": int(time.time() * 1000) + data.get("expires_in", 3600) * 1000,
        }
    except Exception as e:
        log_error(f"Token refresh error: {e}")
        return None


def get_valid_access_token(provider_id: str = "openai") -> str | None:
    """Get a valid access token for a provider.

    Automatically refreshes if expired. Updates auth.json with new tokens.
    Returns the access token, or None if unavailable.
    """
    oauth_data = get_oauth_token(provider_id)
    if not oauth_data:
        log_warning(f"No OAuth token found for provider: {provider_id}")
        return None

    access_token = oauth_data.get("access")
    refresh_token = oauth_data.get("refresh")
    expires = oauth_data.get("expires", 0)
    account_id = oauth_data.get("accountId")

    if not access_token or not refresh_token:
        log_warning(f"Incomplete OAuth data for provider: {provider_id}")
        return None

    now_ms = time.time() * 1000
    if expires > now_ms + TOKEN_REFRESH_BUFFER_MS:
        log_debug(f"OAuth token for {provider_id} is still valid")
        return access_token

    log_debug(f"OAuth token for {provider_id} is expired, refreshing...")

    new_tokens = _refresh_oauth_token(refresh_token)
    if not new_tokens:
        log_error(f"Failed to refresh OAuth token for {provider_id}")
        return None

    auth = load_auth()
    if provider_id in auth:
        auth[provider_id]["access"] = new_tokens["access"]
        auth[provider_id]["refresh"] = new_tokens["refresh"]
        auth[provider_id]["expires"] = new_tokens["expires"]
        if account_id:
            auth[provider_id]["accountId"] = account_id
        save_auth(auth)

    return new_tokens["access"]


def get_account_id(provider_id: str = "openai") -> str | None:
    """Get the account ID for a provider from auth.json."""
    oauth_data = get_oauth_token(provider_id)
    if not oauth_data:
        return None
    return oauth_data.get("accountId")


def is_oauth_available(provider_id: str = "openai") -> bool:
    """Check if OAuth token is available for a provider."""
    return get_oauth_token(provider_id) is not None


ALLOWED_CODEX_MODELS = {
    "gpt-5.5",
    "gpt-5.2",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.4",
    "gpt-5.4-mini",
}

CODEX_MODEL_NAMES = {
    "gpt-5.5": "GPT-5.5",
    "gpt-5.2": "GPT-5.2",
    "gpt-5.3-codex": "GPT-5.3 Codex",
    "gpt-5.3-codex-spark": "GPT-5.3 Codex Spark",
    "gpt-5.4": "GPT-5.4",
    "gpt-5.4-mini": "GPT-5.4 Mini",
}


def _is_codex_model_allowed(model_id: str) -> bool:
    """Check if a model ID is allowed for Codex API.

    Logic:
    1. If in ALLOWED_CODEX_MODELS, return True
    2. If matches gpt-X.Y pattern and version > 5.4, return True
    """
    if model_id in ALLOWED_CODEX_MODELS:
        return True
    import re
    match = re.match(r"^gpt-(\d+\.\d+)", model_id)
    if match:
        version = float(match.group(1))
        return version > 5.4
    return False


GPT_55_LIMIT = {"context": 400000, "input": 272000, "output": 128000}


def get_codex_models(fetch_models: bool = True) -> list[dict[str, Any]]:
    """Get the list of available Codex models.

    If fetch_models is True, fetches from models.dev and filters.
    Otherwise returns hardcoded list.

    Returns list of dicts with: id, name, limit (context, input, output)
    """
    if not fetch_models:
        return [
            {"id": k, "name": CODEX_MODEL_NAMES.get(k, k), "limit": GPT_55_LIMIT if k == "gpt-5.5" else None}
            for k in sorted(ALLOWED_CODEX_MODELS)
        ]

    try:
        import httpx
        resp = httpx.get("https://models.dev/api.json", timeout=10.0)
        if resp.status_code != 200:
            log_warning(f"Failed to fetch models.dev: {resp.status_code}")
            return get_codex_models(fetch_models=False)

        data = resp.json()
        openai_provider = data.get("openai", {})
        models_raw = openai_provider.get("models", {})

        result = []
        for model_id, model_info in models_raw.items():
            if _is_codex_model_allowed(model_id):
                name = model_info.get("name", CODEX_MODEL_NAMES.get(model_id, model_id))
                limit_raw = model_info.get("limit", {})
                if model_id == "gpt-5.5":
                    limit = GPT_55_LIMIT
                else:
                    limit = {
                        "context": limit_raw.get("context"),
                        "input": limit_raw.get("input"),
                        "output": limit_raw.get("output"),
                    } if limit_raw else None
                result.append({"id": model_id, "name": name, "limit": limit})

        return sorted(result, key=lambda m: m["id"])
    except Exception as e:
        log_warning(f"Failed to fetch Codex models: {e}")
        return get_codex_models(fetch_models=False)
