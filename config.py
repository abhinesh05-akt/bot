import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    # Default limits
    DEFAULT_AI_LIMIT = 10
    
    SET_DEFAULT_AI_LIMIT = 20
    SET_USER_AI_LIMIT = 50

    # Database tables
    TABLE_USERS = "users"
    TABLE_ADMINS = "admins"
    TABLE_CHANNELS = "channels"
    TABLE_AI_USAGE = "ai_usage"
    TABLE_SCHEDULED_MSGS = "scheduled_messages"
    TABLE_JOIN_REQUESTS = "join_requests"
    TABLE_BOT_UPDATES = "bot_updates"
