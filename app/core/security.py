"""
Security middleware and utilities
Implements constant-time token comparison and authorization
Follows specifications from 04-Security-Guardrails.md

Fixes applied:
- BUG 4: Added centralized FastAPI dependency for route protection
- BUG 8: Uses config.settings instead of raw os.getenv()
"""

import secrets
import logging
from fastapi import Header, HTTPException, Request, status
from typing import Optional

from app.core.config import settings

logger = logging.getLogger("jit_news_bot")


def verify_telegram_token(x_telegram_bot_api_secret_token: Optional[str] = Header(None)) -> bool:
    """
    Verify Telegram webhook request using constant-time comparison
    Uses X-Telegram-Bot-Api-Secret-Token header
    """
    expected_token = settings.telegram_secret_token

    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="TELEGRAM_SECRET_TOKEN not configured"
        )

    if not x_telegram_bot_api_secret_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing secret token header"
        )

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(x_telegram_bot_api_secret_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid secret token"
        )

    return True


def verify_cron_token(x_cron_secret_token: Optional[str] = Header(None)) -> bool:
    """
    Verify Cron-job.org request using constant-time comparison
    Uses custom header (configured in Cron-job.org)
    """
    expected_token = settings.cron_secret_token

    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CRON_SECRET_TOKEN not configured"
        )

    if not x_cron_secret_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing cron secret token header"
        )

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(x_cron_secret_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid cron secret token"
        )

    return True


def verify_admin_chat_id(chat_id) -> bool:
    """
    Verify that the chat_id matches the admin.
    Only the admin can issue bot commands.
    Uses constant-time comparison per 04-Security-Guardrails.md spec.
    """
    admin_chat_id = settings.admin_chat_id

    if not admin_chat_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_CHAT_ID not configured"
        )

    # Constant-time comparison (BUG 7 fix — was using plain != operator)
    if not secrets.compare_digest(str(chat_id), str(admin_chat_id)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized: only admin can issue commands"
        )

    return True


def validate_time_format(time_str: str) -> bool:
    """
    Validate that a time string matches HH:MM format.
    BUG 10 fix — prevents garbage values from being stored.
    Returns True if valid, raises HTTPException if invalid.
    """
    import re
    if not re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', time_str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid time format '{time_str}'. Use HH:MM (24-hour format, e.g. 08:00 or 15:30)"
        )
    return True
