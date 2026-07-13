"""
GitHub App authentication.
Generates JWTs and exchanges them for per-installation access tokens,
enabling DriftGuard to act on any repo that installs the app.
"""

import os
import time
import jwt
import requests

APP_ID = os.getenv("GITHUB_APP_ID", "")
PRIVATE_KEY_PATH = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", "")
PRIVATE_KEY_CONTENT = os.getenv("GITHUB_APP_PRIVATE_KEY", "")

_token_cache = {}  # installation_id -> (token, expires_at)


def _read_private_key() -> str:
    """Reads the private key either from an env var (preferred in k8s) or a file path."""
    if PRIVATE_KEY_CONTENT:
        return PRIVATE_KEY_CONTENT
    if PRIVATE_KEY_PATH:
        with open(PRIVATE_KEY_PATH, "r") as f:
            return f.read()
    raise ValueError("No GitHub App private key found — set GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH")


def generate_jwt() -> str:
    """Creates a short-lived JWT proving this request comes from our GitHub App."""
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (9 * 60),
        "iss": APP_ID,
    }
    private_key = _read_private_key()
    return jwt.encode(payload, private_key, algorithm="RS256")


def get_installation_token(installation_id: int) -> str:
    """
    Returns a valid access token scoped to one specific installation (repo/org).
    Caches it until near expiry to avoid unnecessary API calls.
    """
    cached = _token_cache.get(installation_id)
    if cached and cached[1] > time.time() + 60:
        return cached[0]

    app_jwt = generate_jwt()
    resp = requests.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["token"]
    expires_at = time.time() + (55 * 60)
    _token_cache[installation_id] = (token, expires_at)
    return token