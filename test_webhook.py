from fastapi.testclient import TestClient
from app.main import app
import os
from dotenv import load_dotenv

load_dotenv()
os.environ["TELEGRAM_SECRET_TOKEN"] = "test"
os.environ["ADMIN_CHAT_ID"] = "8739997260"

client = TestClient(app)

response = client.post(
    "/webhook",
    headers={"x-telegram-bot-api-secret-token": "test"},
    json={
        "message": {
            "chat": {"id": 8739997260},
            "text": "/start"
        }
    }
)
print("STATUS CODE:", response.status_code)
print("RESPONSE:", response.json())
