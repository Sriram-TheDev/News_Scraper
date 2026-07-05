"""
Security middleware and utilities
Implements constant-time token comparison and authorization
Follows specifications from 04-Security-Guardrails.md
"""

import os
import secrets
from fastapi import Header, HTTPException, Request, status
from typing import Optional


def verify_telegram_token(x_telegram_bot_api_secret_token: Optional[str] = Header(None)) -> bool:
    """
    Verify Telegram webhook request using constant-time comparison
    Uses X-Telegram-Bot-Api-Secret-Token header
    """
    expected_token = os.getenv("TELEGRAM_SECRET_TOKEN")
    
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
    expected_token = os.getenv("CRON_SECRET_TOKEN")
    
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


def verify_admin_chat_id(chat_id: str) -> bool:
    """
    Verify that the chat_id matches the admin
    Only the admin can issue bot commands
    """
    admin_chat_id = os.getenv("ADMIN_CHAT_ID")
    
    if not admin_chat_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_CHAT_ID not configured"
        )
    
    if str(chat_id) != str(admin_chat_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized: only admin can issue commands"
        )
    
    return True
