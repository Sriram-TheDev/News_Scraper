"""
Comprehensive test suite for JIT News Vault
Tests security, validation, LLM parsing, and API endpoints
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

# Set required env vars BEFORE importing app modules
os.environ["TELEGRAM_SECRET_TOKEN"] = "test_secret_token"
os.environ["CRON_SECRET_TOKEN"] = "test_cron_secret"
os.environ["ADMIN_CHAT_ID"] = "123456789"
# Setting up tests for Groq
os.environ["GROQ_API_KEY"] = "mock_key"
os.environ["SUPABASE_URL"] = "http://mock.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "mock_key"
os.environ["FIRECRAWL_API_KEY"] = "mock_key"
os.environ["TELEGRAM_BOT_TOKEN"] = "mock_bot_token"

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# ==============================================================================
# Health Check
# ==============================================================================
def test_health_check():
    """Verify that the health check endpoint returns 200 OK without auth"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

# ==============================================================================
# Auth / Security Tests
# ==============================================================================
def test_webhook_missing_token():
    """Verify webhook rejects requests with no secret token"""
    response = client.post("/webhook", json={})
    assert response.status_code == 401

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

def test_cron_digest_missing_token():
    """Verify cron endpoint rejects requests with no token"""
    response = client.post("/cron-digest", json={})
    assert response.status_code == 401

@patch("app.main.get_db")
@patch("app.main.get_telegram_bot")
def test_webhook_authorized_but_ignored(mock_bot, mock_db):
    """Verify webhook correctly ignores payloads without chat_id safely"""
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


# ==============================================================================
# LLM Schema Normalization Tests
# ==============================================================================
class TestLLMSchemaNormalization:
    """Test schema validation/normalization with soft fallbacks"""

    def _get_processor(self):
        from app.services.llm import LLMProcessor
        with patch('app.services.llm.AsyncGroq'):
            return LLMProcessor()

    def test_digest_complete_schema(self):
        """Complete schema should pass through unchanged"""
        proc = self._get_processor()
        result = proc._normalize_digest_schema({
            "title": "Headline", "image_url": "https://img.com/a.jpg",
            "summary": "Info", "source_link": "https://example.com"
        })
        assert result["title"] == "Headline"

    def test_digest_missing_image_gets_default(self):
        """Missing image_url should get empty string default"""
        proc = self._get_processor()
        result = proc._normalize_digest_schema({"title": "Test", "summary": "Info"})
        assert result["image_url"] == ""

    def test_digest_headline_mapped_to_title(self):
        """LLM returning 'headline' instead of 'title' should be remapped"""
        proc = self._get_processor()
        result = proc._normalize_digest_schema({"headline": "Test", "summary": "Info"})
        assert result["title"] == "Test"
        assert "headline" not in result

    def test_digest_both_missing_raises(self):
        """Missing both title AND summary should raise ValueError"""
        proc = self._get_processor()
        with pytest.raises(ValueError, match="missing both"):
            proc._normalize_digest_schema({"image_url": "test.jpg"})

    def test_digest_rejects_base64_image(self):
        """Base64 image URLs should be rejected"""
        proc = self._get_processor()
        result = proc._normalize_digest_schema({
            "title": "Test", "summary": "Info",
            "image_url": "data:image/png;base64,iVBORw0KGgoAAAA"
        })
        assert result["image_url"] == ""

    def test_digest_rejects_webp_image(self):
        """WebP image URLs should be rejected"""
        proc = self._get_processor()
        result = proc._normalize_digest_schema({
            "title": "Test", "summary": "Info",
            "image_url": "https://example.com/image.webp"
        })
        assert result["image_url"] == ""

    def test_live_report_minimal_schema(self):
        """Live reports should work with just title + summary"""
        proc = self._get_processor()
        result = proc._normalize_live_report_schema({"title": "Report", "summary": "Details"})
        assert result["title"] == "Report"
        assert result["source_link"] == ""

    def test_live_report_content_mapped_to_summary(self):
        """LLM returning 'content' instead of 'summary' should be remapped"""
        proc = self._get_processor()
        result = proc._normalize_live_report_schema({"title": "Test", "content": "Details"})
        assert result["summary"] == "Details"


# ==============================================================================
# Time Format Validation Tests (BUG 10)
# ==============================================================================
class TestTimeValidation:
    """Test /settime input validation"""

    def test_valid_times(self):
        from app.core.security import validate_time_format
        assert validate_time_format("00:00") is True
        assert validate_time_format("08:30") is True
        assert validate_time_format("15:00") is True
        assert validate_time_format("23:59") is True

    def test_invalid_times(self):
        from app.core.security import validate_time_format
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException):
            validate_time_format("25:00")
        with pytest.raises(HTTPException):
            validate_time_format("abc")
        with pytest.raises(HTTPException):
            validate_time_format("8:30")   # Missing leading zero
        with pytest.raises(HTTPException):
            validate_time_format("24:00")
        with pytest.raises(HTTPException):
            validate_time_format("12:60")


# ==============================================================================
# Database Column Name Test (BUG 6)
# ==============================================================================
class TestDatabaseColumnName:
    """Verify delete_old_digest_buffers uses the correct column name"""

    def test_uses_generated_at_column(self):
        """The delete query must target 'generated_at', not 'created_at'"""
        import inspect
        from app.core.database import Database
        source = inspect.getsource(Database.delete_old_digest_buffers)
        # Verify the actual Supabase .lt() query targets the correct column
        assert '.lt("generated_at"' in source, "delete_old_digest_buffers must query 'generated_at' column"
        assert '.lt("created_at"' not in source, "delete_old_digest_buffers must NOT use 'created_at' (wrong column name)"
