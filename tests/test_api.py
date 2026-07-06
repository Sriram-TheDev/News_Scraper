from fastapi.testclient import TestClient
from app.main import app
import os
import pytest
from unittest.mock import patch, MagicMock

# Set required env vars for testing module import
os.environ["TELEGRAM_SECRET_TOKEN"] = "test_secret_token"
os.environ["CRON_SECRET_TOKEN"] = "test_cron_secret"
os.environ["ADMIN_CHAT_ID"] = "123456789"
os.environ["GEMINI_API_KEY"] = "mock_key"
os.environ["SUPABASE_URL"] = "http://mock.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "mock_key"

client = TestClient(app)

def test_health_check():
    """Verify that the health check endpoint returns 200 OK without auth"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

def test_webhook_unauthorized_token():
    """Verify webhook rejects invalid x-telegram-bot-api-secret-token"""
    response = client.post(
        "/webhook",
        headers={"x-telegram-bot-api-secret-token": "wrong_token"},
        json={}
    )
    assert response.status_code == 401
    assert "Invalid secret token" in response.json()["detail"]

def test_cron_digest_unauthorized_token():
    """Verify cron endpoint rejects invalid secret token"""
    response = client.post(
        "/cron-digest",
        headers={"x-cron-secret-token": "wrong_token"},
        json={}
    )
    assert response.status_code == 401
    assert "Invalid cron secret token" in response.json()["detail"]

@patch("app.main.get_db")
@patch("app.main.get_telegram_bot")
def test_webhook_authorized_but_ignored(mock_bot, mock_db):
    """Verify webhook correctly ignores payloads without chat_id safely"""
    # Setup mock bot to return None for chat_id extraction
    mock_instance = MagicMock()
    mock_instance.get_chat_id_from_update.return_value = None
    mock_bot.return_value = mock_instance
    
    response = client.post(
        "/webhook",
        headers={"x-telegram-bot-api-secret-token": "test_secret_token"},
        json={"update_id": 12345}
    )
    
    assert response.status_code == 200
    assert response.json() == {"status": "ignored"}
