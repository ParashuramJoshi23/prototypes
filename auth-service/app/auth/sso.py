"""OIDC-based SSO helpers.

Each tenant configures its own OIDC provider (Okta, Azure AD, Auth0, etc.)
via the Tenant model. At login the service:
  1. Discovers the OIDC metadata from <issuer>/.well-known/openid-configuration
  2. Redirects the user to the provider's authorization endpoint
  3. On callback, exchanges the code for tokens and fetches the id_token claims
"""
import secrets
from typing import Optional
from urllib.parse import urlencode

import httpx


def generate_state() -> str:
    return secrets.token_urlsafe(32)


async def discover_oidc_config(issuer: str) -> dict:
    discovery_url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    async with httpx.AsyncClient() as client:
        resp = await client.get(discovery_url, timeout=10)
        resp.raise_for_status()
        return resp.json()


def sso_auth_url(
    authorization_endpoint: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    nonce: Optional[str] = None,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
    }
    if nonce:
        params["nonce"] = nonce
    return f"{authorization_endpoint}?{urlencode(params)}"


async def sso_exchange_code(
    token_endpoint: str,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def sso_get_user(userinfo_endpoint: str, access_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()
