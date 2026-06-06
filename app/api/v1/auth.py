"""
Authentication API routes.
Login, register, refresh tokens, logout, password management.
"""
import logging
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db
from app.services.auth_service import AuthService
from app.services.user_service import UserService, _serialize_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    organization_name: str | None = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    new_password: SecretStr = Field(min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: SecretStr
    new_password: SecretStr = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    is_active: bool
    is_verified: bool
    role: str
    created_at: str

    class Config:
        from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(
    payload: RegisterRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new user account.

    - Creates user record
    - Optionally creates a personal organization
    - Sends email verification link (background task)
    """
    auth_svc = AuthService(db)
    user_svc = UserService(db)

    existing = await user_svc.get_by_email(payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )

    user = await user_svc.create_user(
        email=payload.email,
        password=payload.password.get_secret_value(),
        full_name=payload.full_name,
        organization_name=payload.organization_name,
    )

    background_tasks.add_task(
        auth_svc.send_verification_email,
        user_id=str(user.id),
        email=user.email,
    )

    logger.info("New user registered: %s", user.email)
    return _serialize_user(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and obtain tokens",
)
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate user credentials and return JWT access + refresh tokens.
    """
    auth_svc = AuthService(db)

    user = await auth_svc.authenticate_user(
        email=payload.email,
        password=payload.password.get_secret_value(),
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact support.",
        )

    access_token = auth_svc.create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role}
    )
    refresh_token = await auth_svc.create_refresh_token(user_id=str(user.id))

    await auth_svc.record_login(
        user_id=str(user.id),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    logger.info("User logged in: %s", user.email)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user={
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": str(user.role),
            "is_active": user.is_active,
            "organization_id": str(user.organization_id) if user.organization_id else None,
        },
    )


@router.post(
    "/token",
    response_model=TokenResponse,
    include_in_schema=False,
    summary="OAuth2 compatible login endpoint",
)
async def login_oauth2(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """OAuth2 password flow for Swagger UI compatibility."""
    auth_svc = AuthService(db)
    user = await auth_svc.authenticate_user(
        email=form_data.username,
        password=form_data.password,
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = auth_svc.create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role}
    )
    refresh_token = await auth_svc.create_refresh_token(user_id=str(user.id))
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
)
async def refresh_token(
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Exchange a valid refresh token for a new access + refresh token pair.
    Old refresh token is invalidated (rotation).
    """
    auth_svc = AuthService(db)

    result = await auth_svc.rotate_refresh_token(payload.refresh_token)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Invalidate session tokens",
)
async def logout(
    payload: RefreshRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Invalidate the provided refresh token and blacklist the current access token.
    """
    auth_svc = AuthService(db)
    await auth_svc.invalidate_refresh_token(payload.refresh_token)
    logger.info("User logged out: %s", current_user.email)


@router.get(
    "/me",
    summary="Get current authenticated user",
)
async def get_me(current_user=Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return _serialize_user(current_user)


@router.get(
    "/verify-email/{token}",
    status_code=status.HTTP_200_OK,
    summary="Verify email address",
)
async def verify_email(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Verify user's email address using the token sent via email."""
    auth_svc = AuthService(db)
    success = await auth_svc.verify_email_token(token)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token.",
        )
    return {"message": "Email verified successfully."}


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request password reset email",
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Send a password reset link to the provided email address.
    Always returns 202 to prevent email enumeration.
    """
    auth_svc = AuthService(db)
    user_svc = UserService(db)

    user = await user_svc.get_by_email(payload.email)
    if user:
        background_tasks.add_task(
            auth_svc.send_password_reset_email,
            user_id=str(user.id),
            email=user.email,
        )

    return {"message": "If an account exists with that email, a reset link has been sent."}


@router.post(
    "/reset-password/{token}",
    status_code=status.HTTP_200_OK,
    summary="Reset password using token",
)
async def reset_password(
    token: str,
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reset password using the token from the reset email."""
    auth_svc = AuthService(db)
    success = await auth_svc.reset_password(
        token=token,
        new_password=payload.new_password.get_secret_value(),
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )
    return {"message": "Password reset successfully."}


@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    summary="Change password for authenticated user",
)
async def change_password(
    payload: ChangePasswordRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the current user's password. Requires current password verification."""
    auth_svc = AuthService(db)
    success = await auth_svc.change_password(
        user_id=str(current_user.id),
        current_password=payload.current_password.get_secret_value(),
        new_password=payload.new_password.get_secret_value(),
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )
    return {"message": "Password changed successfully."}
