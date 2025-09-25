# services/june-orchestrator/shared/__init__.py
import os
import httpx

def get_keycloak_settings() -> dict:
    base = os.getenv("KEYCLOAK_URL") or os.getenv("KC_BASE_URL")
    realm = os.getenv("KEYCLOAK_REALM") or os.getenv("KC_REALM") or "june"
    if not base:
        raise RuntimeError("KEYCLOAK_URL (or KC_BASE_URL) is not set")
    base = base.rstrip("/")
    return {
        "base": base,
        "realm": realm,
        "discovery": f"{base}/realms/{realm}/.well-known/openid-configuration",  # hyphen!
    }

async def get_oidc_configuration() -> dict:
    cfg = get_keycloak_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(cfg["discovery"])
        r.raise_for_status()
        return r.json()
