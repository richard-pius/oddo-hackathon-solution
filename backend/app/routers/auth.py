"""
Auth Router — Brightloop
==========================
Handles customer signup, login, JWT issuance, forgot/reset password,
and admin-only staff account creation.

Why cookies AND JSON response:
  The Astro frontend reads the JSON body to update local state (show the
  user's name, redirect based on role). But the actual auth token goes in
  an HTTP-only cookie so XSS can never steal it. Belt and suspenders.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    User, UserRole, PasswordResetToken,
    Subscription, SubscriptionLine, SubscriptionAudit, Invoice, InvoiceLine, Payment,
)
from app.schemas import (
    UserRegister, UserLogin, TokenResponse, UserOut,
    ForgotPasswordRequest, ResetPasswordRequest, StaffCreate, AdminUserPasswordChange,
)
from app.services.auth_service import (
    hash_password, verify_password, create_access_token,
    get_current_user, require_admin, require_staff_or_admin,
    create_reset_token,
)
from app.config import settings

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register_customer(data: UserRegister, response: Response, db: AsyncSession = Depends(get_db)):
    """
    Customer self-signup. Creates a CUSTOMER-role user.
    Staff and admin accounts are created separately by admins.
    """
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        role=UserRole.CUSTOMER,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id, user.role.value)

    # Set HTTP-only cookie for browser-based auth
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        path="/",
    )

    return TokenResponse(
        access_token=token,
        role=user.role.value,
        user_id=user.id,
        full_name=user.full_name,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate and return JWT token + set cookie. Supports both JSON and Form data."""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            email = body.get("email") or body.get("username", "")
            password = body.get("password", "")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
    else:
        form = await request.form()
        email = form.get("username") or form.get("email", "")
        password = form.get("password", "")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(str(password), user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")

    token = create_access_token(user.id, user.role.value)

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        path="/",
    )

    return TokenResponse(
        access_token=token,
        role=user.role.value,
        user_id=user.id,
        full_name=user.full_name,
    )


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(key="access_token", path="/")
    return {"detail": "Logged out"}


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """
    Generates a time-limited reset token. In production this would dispatch
    an email; for the hackathon we return the token directly (insecure but
    demonstrable).
    """
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    # Why we always return 200: timing attacks can reveal which emails are
    # registered if we return 404 for unknown emails.
    if not user:
        return {"detail": "If the email is registered, a reset link has been sent."}

    token = create_reset_token()
    reset = PasswordResetToken(
        user_id=user.id,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.RESET_TOKEN_EXPIRE_MINUTES),
    )
    db.add(reset)
    await db.commit()

    # In production: send_email(user.email, reset_link=f"...?token={token}")
    return {
        "detail": "If the email is registered, a reset link has been sent.",
        "debug_token": token,  # Remove in production
    }


@router.post("/reset-password")
async def reset_password(data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Verify the reset token and update the user's password."""
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token == data.token,
            PasswordResetToken.used == False,
            PasswordResetToken.expires_at > datetime.now(timezone.utc),
        )
    )
    reset_record = result.scalar_one_or_none()

    if not reset_record:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")

    user_result = await db.execute(select(User).where(User.id == reset_record.user_id))
    user = user_result.scalar_one()

    user.hashed_password = hash_password(data.new_password)
    reset_record.used = True
    await db.commit()

    return {"detail": "Password updated successfully"}


# ─── Admin-Only Staff Creation ────────────────────────────────────────────────

@router.post("/staff", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_staff(
    data: StaffCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Only an Admin can create INTERNAL_STAFF accounts.
    Why not let staff self-register: prevents unauthorized access escalation.
    A rogue employee could create phantom staff accounts for data exfiltration.
    """
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        role=UserRole.INTERNAL_STAFF,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin-only: list all users for staff management."""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.delete("/users/{user_id}", status_code=status.HTTP_200_OK)
async def delete_user_account(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Admin-only: Delete another user account.
    Prevents self-deletion to preserve administrative access.
    Safely cascades any dependencies.
    """
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Administrators cannot delete their own active account."
        )

    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User account not found")

    # 1. Delete password reset tokens
    await db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id))

    # 2. Reassign staff references if target was staff/admin
    await db.execute(
        update(SubscriptionAudit).where(SubscriptionAudit.changed_by_id == user_id).values(changed_by_id=admin.id)
    )
    await db.execute(
        update(Payment).where(Payment.recorded_by_id == user_id).values(recorded_by_id=admin.id)
    )

    # 3. Clean up customer subscriptions & invoices if deleting a customer
    inv_res = await db.execute(select(Invoice.id).where(Invoice.customer_id == user_id))
    inv_ids = inv_res.scalars().all()
    if inv_ids:
        await db.execute(delete(Payment).where(Payment.invoice_id.in_(inv_ids)))
        await db.execute(delete(InvoiceLine).where(InvoiceLine.invoice_id.in_(inv_ids)))
        await db.execute(delete(Invoice).where(Invoice.id.in_(inv_ids)))

    sub_res = await db.execute(select(Subscription.id).where(Subscription.customer_id == user_id))
    sub_ids = sub_res.scalars().all()
    if sub_ids:
        await db.execute(delete(SubscriptionAudit).where(SubscriptionAudit.subscription_id.in_(sub_ids)))
        await db.execute(delete(SubscriptionLine).where(SubscriptionLine.subscription_id.in_(sub_ids)))
        await db.execute(delete(Subscription).where(Subscription.id.in_(sub_ids)))

    user_email = target_user.email
    await db.delete(target_user)
    await db.commit()

    return {"detail": f"Account {user_email} has been permanently deleted."}


@router.put("/users/{user_id}/password", status_code=status.HTTP_200_OK)
async def admin_change_user_password(
    user_id: int,
    data: AdminUserPasswordChange,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Admin-only: Change or reset any user account password.
    Enforces strict enterprise password complexity requirements.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User account not found")

    target_user.hashed_password = hash_password(data.password)
    await db.commit()

    return {"detail": f"Password for {target_user.email} updated successfully."}
