"""
Auth Service — Brightloop
==========================
Handles user registration, JWT issuance, password resets, and RBAC enforcement.

Why bcrypt instead of argon2:
  argon2 is theoretically stronger, but bcrypt is battle-tested in production
  ERP systems for 15+ years. The real risk isn't algorithm weakness — it's
  developer error (storing plaintext, leaking tokens). We mitigate that by
  keeping all password operations inside this single module.

Why HTTP-only cookie + Bearer dual support:
  The Astro frontend uses HTTP-only cookies (immune to XSS token theft).
  API consumers and mobile apps use Bearer tokens. Both are validated by the
  same `get_current_user` dependency so we never maintain two auth paths.
"""

import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User, UserRole, PasswordResetToken

# ─── Password Hashing ────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ─── JWT Token Management ────────────────────────────────────────────────────

def create_access_token(user_id: int, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# ─── Password Reset Token ────────────────────────────────────────────────────

def create_reset_token() -> str:
    """Generate a cryptographically random URL-safe token for password resets."""
    return secrets.token_urlsafe(48)


# ─── FastAPI Dependencies — Current User Extraction ──────────────────────────

security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Why we check cookies first, then Bearer:
    Browser requests from the Astro frontend send HTTP-only cookies automatically.
    API clients (Postman, mobile) send Authorization headers. Checking both means
    neither workflow needs special-casing in the router decorators.
    """
    token = None

    # 1. Explicit Authorization Bearer header takes precedence (API clients & tests)
    if credentials:
        token = credentials.credentials

    # 2. Ambient HTTP-only cookie (Astro frontend browser requests)
    if not token:
        cookie_token = request.cookies.get("access_token")
        if cookie_token:
            token = cookie_token

    # 3. Query param token (for browser EventSource SSE streams & direct PDF links)
    if not token:
        token = request.query_params.get("token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    payload = decode_access_token(token)
    user_id = int(payload["sub"])

    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


# ─── RBAC Dependency Factories ───────────────────────────────────────────────
# Why factory functions instead of a decorator:
# FastAPI's dependency injection composes cleanly. `Depends(require_role(ADMIN))`
# reads like English and is trivially testable by mocking get_current_user.

def require_role(*allowed_roles: UserRole):
    """Returns a dependency that enforces the user has one of the allowed roles."""
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role {current_user.role.value} is not authorized. Required: {[r.value for r in allowed_roles]}",
            )
        return current_user
    return role_checker


# Convenience aliases used across routers
require_admin = require_role(UserRole.ADMIN)
require_staff_or_admin = require_role(UserRole.ADMIN, UserRole.INTERNAL_STAFF)
require_any_authenticated = require_role(UserRole.ADMIN, UserRole.INTERNAL_STAFF, UserRole.CUSTOMER)
