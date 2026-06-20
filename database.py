import requests
from config import Config
import json
from datetime import datetime, date

class Database:
    def __init__(self):
        self.url = Config.SUPABASE_URL.strip() if Config.SUPABASE_URL else ""
        self.key = Config.SUPABASE_KEY.strip() if Config.SUPABASE_KEY else ""

        print(f"[DEBUG] Supabase URL: {self.url[:40]}...")
        print(f"[DEBUG] Supabase Key length: {len(self.key)}")
        print(f"[DEBUG] Key starts with: {self.key[:20] if self.key else 'EMPTY'}")

        if not self.url or not self.key:
            raise ValueError("SUPABASE_URL or SUPABASE_KEY is missing! Check your .env or Hugging Face secrets.")

        self.rest_url = f"{self.url}/rest/v1"
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

    def _get(self, endpoint, params=None):
        r = requests.get(f"{self.rest_url}/{endpoint}", headers=self.headers, params=params)
        return r.json() if r.status_code == 200 else []

    def _post(self, endpoint, data):
        r = requests.post(f"{self.rest_url}/{endpoint}", headers=self.headers, json=data)
        return r.json() if r.status_code in [200, 201] else None

    def _patch(self, endpoint, data, params=None):
        r = requests.patch(f"{self.rest_url}/{endpoint}", headers=self.headers, json=data, params=params)
        return r.json() if r.status_code in [200, 204] else None

    def _delete(self, endpoint, params=None):
        r = requests.delete(f"{self.rest_url}/{endpoint}", headers=self.headers, params=params)
        return r.status_code in [200, 204]

    # ========== USERS ==========
    def get_user(self, user_id):
        data = self._get(f"{Config.TABLE_USERS}", {"user_id": f"eq.{user_id}"})
        return data[0] if data else None

    def create_user(self, user_id, username, first_name):
        data = {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "created_at": datetime.utcnow().isoformat(),
            "ai_requests_today": 0,
            "last_ai_request_date": str(date.today()),
            "is_banned": False
        }
        self._post(Config.TABLE_USERS, data)
        return data

    def update_user_ai_usage(self, user_id):
        today = str(date.today())
        user = self.get_user(user_id)
        if user and user.get("last_ai_request_date") == today:
            self._patch(Config.TABLE_USERS, {"ai_requests_today": user["ai_requests_today"] + 1}, {"user_id": f"eq.{user_id}"})
        else:
            self._patch(Config.TABLE_USERS, {"ai_requests_today": 1, "last_ai_request_date": today}, {"user_id": f"eq.{user_id}"})

    def reset_ai_usage(self, user_id):
        self._patch(Config.TABLE_USERS, {"ai_requests_today": 0, "last_ai_request_date": str(date.today())}, {"user_id": f"eq.{user_id}"})

    def get_all_users(self):
        return self._get(Config.TABLE_USERS)

    def set_default_ai_limit(self, limit):
        """Updates ai_limit for all non-owner users who still have the default limit."""
        # Store the new default in a config/settings table, or update all users
        # Here we update every user row that hasn't had a custom limit set
        users = self.get_all_users()
        for user in users:
            if user.get("ai_limit") == Config.DEFAULT_AI_LIMIT or user.get("ai_limit") is None:
                self._patch(Config.TABLE_USERS, {"ai_limit": limit}, {"user_id": f"eq.{user['user_id']}"})
        # Also update the in-memory default so new users get the right limit
        Config.DEFAULT_AI_LIMIT = limit

    # ========== ADMINS ==========
    def get_admin(self, user_id):
        data = self._get(f"{Config.TABLE_ADMINS}", {"user_id": f"eq.{user_id}"})
        return data[0] if data else None

    def add_admin(self, user_id, added_by):
        data = {"user_id": user_id, "added_by": added_by, "created_at": datetime.utcnow().isoformat()}
        self._post(Config.TABLE_ADMINS, data)
        return data

    def remove_admin(self, user_id):
        return self._delete(Config.TABLE_ADMINS, {"user_id": f"eq.{user_id}"})

    def get_all_admins(self):
        return self._get(Config.TABLE_ADMINS)

    # ========== CHANNELS ==========
    def get_channel(self, channel_id):
        data = self._get(f"{Config.TABLE_CHANNELS}", {"channel_id": f"eq.{channel_id}"})
        return data[0] if data else None

    def add_channel(
        self,
        channel_id,
        channel_name,
        invite_link,
        added_by,
        auto_approve=False
    ):
        data = {
            "channel_id": channel_id,
            "channel_name": channel_name,
            "invite_link": invite_link,
            "added_by": added_by,
            "auto_approve": auto_approve,
            "created_at": datetime.utcnow().isoformat()
        }
    
        self._post(Config.TABLE_CHANNELS, data)
    
        return data

    def update_channel_invite_link(self, channel_id, invite_link):
        self._patch(Config.TABLE_CHANNELS, {"invite_link": invite_link}, {"channel_id": f"eq.{channel_id}"})

    def remove_channel(self, channel_id):
        return self._delete(Config.TABLE_CHANNELS, {"channel_id": f"eq.{channel_id}"})

    def get_all_channels(self):
        return self._get(Config.TABLE_CHANNELS)

    def update_channel_auto_approve(self, channel_id, auto_approve):
        self._patch(Config.TABLE_CHANNELS, {"auto_approve": auto_approve}, {"channel_id": f"eq.{channel_id}"})

    # ========== AI USAGE LOG ==========
    def log_ai_request(self, user_id, prompt, response):
        data = {"user_id": user_id, "prompt": prompt, "response": response, "created_at": datetime.utcnow().isoformat()}
        self._post(Config.TABLE_AI_USAGE, data)

    # ========== SCHEDULED MESSAGES ==========
    def add_scheduled_message(self, user_id, target_type, target_id, message_text, schedule_time, 
                               media_type=None, media_file_id=None, media_caption=None,
                               reply_markup_json=None):
        data = {
            "user_id": user_id,
            "target_type": target_type,
            "target_id": target_id,
            "message_text": message_text,
            "media_type": media_type,
            "media_file_id": media_file_id,
            "media_caption": media_caption,
            "reply_markup_json": reply_markup_json,
            "schedule_time": schedule_time.isoformat(),
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        }
        result = self._post(Config.TABLE_SCHEDULED_MSGS, data)
        return result[0] if result else None

    def get_pending_messages(self):
        return self._get(Config.TABLE_SCHEDULED_MSGS, {"status": "eq.pending"})

    def update_message_status(self, msg_id, status):
        self._patch(Config.TABLE_SCHEDULED_MSGS, {"status": status}, {"id": f"eq.{msg_id}"})

    def get_user_scheduled_messages(self, user_id):
        return self._get(Config.TABLE_SCHEDULED_MSGS, {"user_id": f"eq.{user_id}"})

    def get_scheduled_message_by_id(self, msg_id):
        """Looks up a scheduled message by its own id, regardless of owner.
        Needed for copyright reports filed against someone else's schedule."""
        data = self._get(Config.TABLE_SCHEDULED_MSGS, {"id": f"eq.{msg_id}"})
        return data[0] if data else None

    def delete_scheduled_message(self, msg_id):
        return self._delete(Config.TABLE_SCHEDULED_MSGS, {"id": f"eq.{msg_id}"})

    # ========== JOIN REQUESTS ==========
    def log_join_request(self, channel_id, user_id, status):
        data = {"channel_id": channel_id, "user_id": user_id, "status": status, "created_at": datetime.utcnow().isoformat()}
        self._post(Config.TABLE_JOIN_REQUESTS, data)

    def get_join_request(self, channel_id, user_id):
        data = self._get(Config.TABLE_JOIN_REQUESTS, {"channel_id": f"eq.{channel_id}", "user_id": f"eq.{user_id}"})
        return data[0] if data else None
    
    def save_join_request(self, user_id, channel_id):
    
        if self.has_join_request(
            user_id,
            channel_id
        ):
            return
    
        data = {
            "user_id": user_id,
            "channel_id": channel_id,
            "status": "verified",
            "created_at": datetime.utcnow().isoformat()
        }
    
        self._post(
            Config.TABLE_JOIN_REQUESTS,
            data
        )
    
        return data
    
    def has_join_request(self, user_id, channel_id):
    
        rows = self._get(
            Config.TABLE_JOIN_REQUESTS,
            {
                "user_id": f"eq.{user_id}",
                "channel_id": f"eq.{channel_id}"
            }
        )
    
        return len(rows) > 0
        
    def add_user_channel(
        self,
        user_id,
        channel_id,
        channel_name
    ):
        data = {
            "user_id": user_id,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "auto_approve": True,
            "created_at": datetime.utcnow().isoformat()
        }
    
        return self._post(
            "user_channels",
            data
        )
    
    def get_user_channel(self, channel_id):
        data = self._get(
            "user_channels",
            {
                "channel_id": f"eq.{channel_id}"
            }
        )
    
        return data[0] if data else None
    
    def get_user_channels(self, user_id):
        return self._get(
            "user_channels",
            {
                "user_id": f"eq.{user_id}"
            }
        )
    
    def remove_user_channel(self, channel_id):
        return self._delete(
            "user_channels",
            {
                "channel_id": f"eq.{channel_id}"
            }
        )
    
    def toggle_auto_approve(
        self,
        channel_id,
        state
    ):
        self._patch(
            "user_channels",
            {
                "auto_approve": state
            },
            {
                "channel_id": f"eq.{channel_id}"
            }
        )

    # ========== BOT UPDATES ==========
    def add_bot_update(self, title, message, added_by):
        data = {"title": title, "message": message, "added_by": added_by, "created_at": datetime.utcnow().isoformat()}
        result = self._post(Config.TABLE_BOT_UPDATES, data)
        return result[0] if result else None

    def get_all_updates(self):
        data = self._get(f"{Config.TABLE_BOT_UPDATES}?order=created_at.desc")
        return data if isinstance(data, list) else []

    def delete_update(self, update_id):
        return self._delete(Config.TABLE_BOT_UPDATES, {"id": f"eq.{update_id}"})

    # ========== COPYRIGHT: BAN / RESTRICTION CHECKS ==========
    def is_user_banned(self, user_id):
        user = self.get_user(user_id)
        return bool(user and user.get("is_banned"))

    def is_user_restricted(self, user_id):
        """Returns the restriction expiry datetime if user is currently
        restricted from scheduling, else None. Restriction is time-bound
        (strike 2); ban (strike 3) is permanent and checked separately."""
        user = self.get_user(user_id)
        if not user:
            return None
        until_str = user.get("restricted_until")
        if not until_str:
            return None
        try:
            until = datetime.fromisoformat(until_str)
        except Exception:
            return None
        if until > datetime.utcnow():
            return until
        return None

    def set_user_banned(self, user_id, banned=True):
        self._patch(Config.TABLE_USERS, {"is_banned": banned}, {"user_id": f"eq.{user_id}"})

    def set_user_restricted_until(self, user_id, until_dt):
        """Pass None to clear the restriction."""
        value = until_dt.isoformat() if until_dt else None
        self._patch(Config.TABLE_USERS, {"restricted_until": value}, {"user_id": f"eq.{user_id}"})

    def has_acknowledged_copyright_warning(self, user_id):
        user = self.get_user(user_id)
        return bool(user and user.get("copyright_warning_ack"))

    def set_copyright_warning_acknowledged(self, user_id):
        self._patch(Config.TABLE_USERS, {"copyright_warning_ack": True}, {"user_id": f"eq.{user_id}"})

    # ========== COPYRIGHT: MEDIA LOG ==========
    def log_scheduled_media(self, user_id, file_id, message_id, media_type, schedule_time, upload_date=None):
        """Records every scheduled copyright-relevant media item for moderation lookup.
        message_id here is the scheduled_messages.id (the schedule's own DB id),
        since the original Telegram message_id isn't retained anywhere upstream."""
        data = {
            "user_id": user_id,
            "file_id": file_id,
            "message_id": message_id,
            "media_type": media_type,
            "schedule_time": schedule_time.isoformat() if hasattr(schedule_time, "isoformat") else str(schedule_time),
            "upload_date": (upload_date or datetime.utcnow()).isoformat(),
            "strike_status": "none",
            "created_at": datetime.utcnow().isoformat()
        }
        result = self._post(Config.TABLE_MEDIA_LOG, data)
        return result[0] if result else None

    def get_media_log_entry(self, log_id):
        data = self._get(Config.TABLE_MEDIA_LOG, {"id": f"eq.{log_id}"})
        return data[0] if data else None

    def get_media_log_by_schedule_id(self, schedule_message_id):
        data = self._get(Config.TABLE_MEDIA_LOG, {"message_id": f"eq.{schedule_message_id}"})
        return data[0] if data else None

    def get_user_media_log(self, user_id):
        return self._get(Config.TABLE_MEDIA_LOG, {"user_id": f"eq.{user_id}", "order": "created_at.desc"})

    def mark_media_log_status(self, log_id, status):
        """status: 'none' | 'flagged' | 'removed' | 'infringing'"""
        self._patch(Config.TABLE_MEDIA_LOG, {"strike_status": status}, {"id": f"eq.{log_id}"})

    # ========== COPYRIGHT: REPORTS ==========
    def create_copyright_report(self, reporter_id, reported_user_id, scheduled_message_id, reason):
        data = {
            "reporter_id": reporter_id,
            "reported_user_id": reported_user_id,
            "scheduled_message_id": scheduled_message_id,
            "reason": reason,
            "status": "open",
            "created_at": datetime.utcnow().isoformat()
        }
        result = self._post(Config.TABLE_COPYRIGHT_REPORTS, data)
        return result[0] if result else None

    def get_all_reports(self):
        return self._get(f"{Config.TABLE_COPYRIGHT_REPORTS}?order=created_at.desc")

    def get_report(self, report_id):
        data = self._get(Config.TABLE_COPYRIGHT_REPORTS, {"id": f"eq.{report_id}"})
        return data[0] if data else None

    def update_report_status(self, report_id, status):
        self._patch(Config.TABLE_COPYRIGHT_REPORTS, {"status": status}, {"id": f"eq.{report_id}"})

    # ========== COPYRIGHT: STRIKES ==========
    def get_user_strike_count(self, user_id):
        rows = self._get(Config.TABLE_COPYRIGHT_STRIKES, {"user_id": f"eq.{user_id}"})
        return len(rows) if rows else 0

    def add_strike(self, user_id, reason, added_by):
        data = {
            "user_id": user_id,
            "reason": reason,
            "added_by": added_by,
            "created_at": datetime.utcnow().isoformat()
        }
        self._post(Config.TABLE_COPYRIGHT_STRIKES, data)
        return self.get_user_strike_count(user_id)

    def get_user_strikes(self, user_id):
        return self._get(Config.TABLE_COPYRIGHT_STRIKES, {"user_id": f"eq.{user_id}", "order": "created_at.desc"})

    def reset_strikes(self, user_id):
        self._delete(Config.TABLE_COPYRIGHT_STRIKES, {"user_id": f"eq.{user_id}"})

    # ========== COPYRIGHT: AUDIT LOG ==========
    def add_audit_log(self, action_type, actor_id, target_user_id, details=""):
        """action_type: 'report' | 'content_removal' | 'warning' | 'restriction' |
        'ban' | 'unban' | 'strike_reset'"""
        data = {
            "action_type": action_type,
            "actor_id": actor_id,
            "target_user_id": target_user_id,
            "details": details,
            "created_at": datetime.utcnow().isoformat()
        }
        self._post(Config.TABLE_AUDIT_LOG, data)

    def get_audit_log(self, limit=50):
        data = self._get(f"{Config.TABLE_AUDIT_LOG}?order=created_at.desc&limit={limit}")
        return data if isinstance(data, list) else []

    def get_user_audit_log(self, user_id):
        return self._get(Config.TABLE_AUDIT_LOG, {"target_user_id": f"eq.{user_id}", "order": "created_at.desc"})

db = Database()
