"""
P1-SEC-1: API 权限控制

Provides:
- Bearer token verification dependency for FastAPI routes
- Role-based access control (RBAC) decorators
- Per-method authorization checks

Usage:
    from app.core.security import verify_bearer_token

    @router.get("/protected")
    async def protected(bearer=Depends(verify_bearer_token)):
        ...
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)


class Role(str, Enum):
    """Available roles for RBAC."""
    ADMIN = "admin"
    USER = "user"
    READONLY = "readonly"
    WEBHOOK = "webhook"


# Map of token -> role. In production this would be a proper user DB.
_TOKEN_ROLE_MAP: dict[str, Role] = {}


def _get_bearer_token(request: Request) -> str | None:
    """Extract bearer token from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def verify_bearer_token(request: Request) -> str:
    """
    FastAPI dependency that verifies the bearer token.

    Raises HTTPException 401 if missing, 403 if invalid.
    Returns the validated token string.
    """
    token = _get_bearer_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # The token stored at startup is the reference
    expected = getattr(request.app.state, "bearer_token", None)
    if not expected or token != expected:
        logger.warning(f"Invalid bearer token attempt from {request.client}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid bearer token",
        )

    return token


def get_token_role(token: str) -> Role:
    """Look up the role for a given token."""
    return _TOKEN_ROLE_MAP.get(token, Role.USER)


def register_token(token: str, role: Role) -> None:
    """Register a token with a specific role (for multi-user setups)."""
    _TOKEN_ROLE_MAP[token] = role


def require_role(required: Role):
    """
    FastAPI dependency factory: requires the caller's token to have at least the given role.

    Usage:
        @router.delete("/sessions/{id}")
        async def delete_session(
            session_id: str,
            bearer=Depends(verify_bearer_token),
            _=Depends(require_role(Role.ADMIN)),
        ):
            ...
    """
    def dependency(bearer: Annotated[str, Depends(verify_bearer_token)]) -> str:
        role = get_token_role(bearer)
        if _role_hierarchy(role) < _role_hierarchy(required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {required.value} role, got {role.value}",
            )
        return bearer

    return dependency


def _role_hierarchy(role: Role) -> int:
    """Numeric level for role comparison (higher = more privilege)."""
    return {"readonly": 0, "user": 1, "webhook": 1, "admin": 2}[role.value]


# ── RPC method auth wrapper ───────────────────────────────────────────────────

def auth_required(func):
    """
    Decorator to wrap @method RPC functions with bearer token auth.

    Usage:
        @method
        @auth_required
        async def delete_session(context, session_id: str):
            ...

    Checks the bearer token from RPC request context.
    """
    async def wrapper(context, *args, **kwargs):
        import json
        # Context should have request headers available via context.request
        req = getattr(context, "request", None)
        if req is None:
            return {"error": "unauthorized", "code": 401}

        token = _get_bearer_token(req)
        expected = getattr(req.app.state, "bearer_token", None)
        if not token or token != expected:
            return {"error": "invalid_token", "code": 403}

        return await func(context, *args, **kwargs)

    return wrapper


# Alias for backwards compatibility with P1-SEC-1 references
require_auth = verify_bearer_token
