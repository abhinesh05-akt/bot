from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta, timezone
from database import db
from telegram import Bot
import asyncio
import logging

logger = logging.getLogger(__name__)

class MessageScheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        # Do NOT start scheduler here — event loop not ready yet.
        # start() is called lazily on first use via _get_scheduler().
        self._scheduler = None

    def _get_scheduler(self):
        """Return the scheduler, starting it inside the running loop if needed."""
        if self._scheduler is None:
            # IMPORTANT: timezone="UTC" is explicit and mandatory here.
            # All schedule_time values throughout this codebase (handlers.py,
            # database.py) are naive UTC datetimes. Without an explicit
            # timezone, AsyncIOScheduler falls back to tzlocal.get_localzone(),
            # which resolves against the container's /etc/localtime — and
            # python:3.11-slim does NOT ship the tzdata package, so that
            # resolution is undefined/inconsistent across environments
            # (worked locally, silently wrong on a different host). Pinning
            # to UTC removes the dependency on container tzdata entirely.
            self._scheduler = AsyncIOScheduler(timezone="UTC")
            try:
                loop = asyncio.get_running_loop()
                self._scheduler._eventloop = loop  # pin to PTB's loop
            except RuntimeError:
                pass  # no running loop yet; APScheduler will find it on first fire
            self._scheduler.start()
            logger.info("APScheduler started inside running event loop (timezone=UTC).")
        return self._scheduler

    def schedule_message(self, msg_id, target_type, target_id, message_text, schedule_time,
                         media_type=None, media_file_id=None, media_caption=None,
                         reply_markup=None):
        trigger = DateTrigger(run_date=schedule_time)
        self._get_scheduler().add_job(
            self._send_scheduled_message,
            trigger=trigger,
            args=[msg_id, target_type, target_id, message_text, media_type, media_file_id,
                  media_caption, reply_markup],
            id=str(msg_id),
            replace_existing=True
        )
        logger.info(f"Scheduled msg_id={msg_id} for {schedule_time} → chat_id={target_id}")

    async def _send_scheduled_message(self, msg_id, target_type, target_id, message_text,
                                       media_type, media_file_id, media_caption, reply_markup):
        # Ensure target_id is int (Supabase may return string)
        try:
            target_id = int(target_id)
        except (TypeError, ValueError):
            pass

        try:
            caption = media_caption or message_text

            if media_type and media_file_id:
                if media_type == 'photo':
                    await self.bot.send_photo(chat_id=target_id, photo=media_file_id,
                                              caption=caption, reply_markup=reply_markup)
                elif media_type == 'video':
                    await self.bot.send_video(chat_id=target_id, video=media_file_id,
                                              caption=caption, reply_markup=reply_markup)
                elif media_type == 'document':
                    await self.bot.send_document(chat_id=target_id, document=media_file_id,
                                                  caption=caption, reply_markup=reply_markup)
                elif media_type == 'audio':
                    await self.bot.send_audio(chat_id=target_id, audio=media_file_id,
                                              caption=caption, reply_markup=reply_markup)
                elif media_type == 'voice':
                    await self.bot.send_voice(chat_id=target_id, voice=media_file_id,
                                              caption=caption, reply_markup=reply_markup)
                elif media_type == 'video_note':
                    await self.bot.send_video_note(chat_id=target_id, video_note=media_file_id)
                elif media_type == 'animation':
                    await self.bot.send_animation(chat_id=target_id, animation=media_file_id,
                                                   caption=caption, reply_markup=reply_markup)
                elif media_type == 'sticker':
                    await self.bot.send_sticker(chat_id=target_id, sticker=media_file_id,
                                                reply_markup=reply_markup)
                elif media_type == 'location':
                    parts = media_file_id.split(',')
                    lat, lng = float(parts[0]), float(parts[1])
                    await self.bot.send_location(chat_id=target_id, latitude=lat, longitude=lng,
                                                  reply_markup=reply_markup)
                elif media_type == 'poll':
                    import json
                    poll_data = json.loads(message_text)
                    await self.bot.send_poll(
                        chat_id=target_id,
                        question=poll_data.get('question', 'Poll'),
                        options=poll_data.get('options', []),
                        is_anonymous=poll_data.get('is_anonymous', True),
                        allows_multiple_answers=poll_data.get('allows_multiple_answers', False)
                    )
                elif media_type == 'contact':
                    parts = media_file_id.split('|')
                    phone = parts[0]
                    first_name = parts[1] if len(parts) > 1 else "Contact"
                    last_name = parts[2] if len(parts) > 2 else ""
                    await self.bot.send_contact(chat_id=target_id, phone_number=phone,
                                                 first_name=first_name, last_name=last_name,
                                                 reply_markup=reply_markup)
            else:
                await self.bot.send_message(chat_id=target_id, text=message_text,
                                             reply_markup=reply_markup, parse_mode="HTML")

            db.update_message_status(msg_id, "sent")
            logger.info(f"[SCHEDULER] msg_id={msg_id} sent successfully to {target_id}")

        except Exception as e:
            error_msg = f"failed: {str(e)}"
            db.update_message_status(msg_id, error_msg)
            logger.error(f"[SCHEDULER ERROR] msg_id={msg_id}: {e}", exc_info=True)

    def remove_scheduled_job(self, msg_id):
        try:
            if self._scheduler:
                self._scheduler.remove_job(str(msg_id))
        except Exception:
            pass


scheduler = None

def init_scheduler(bot):
    global scheduler
    scheduler = MessageScheduler(bot)
    return scheduler


async def reschedule_pending_messages():
    """
    Called from post_init (async context, inside PTB's running loop).
    Re-registers any 'pending' DB messages into APScheduler.
    Must be async so that _get_scheduler() pins to the correct loop.
    """
    if not scheduler:
        logger.warning("reschedule_pending_messages called before init_scheduler")
        return

    pending = db.get_pending_messages()
    now = datetime.utcnow()  # DB stores UTC, compare in UTC
    restored, missed = 0, 0

    for msg in pending:
        try:
            schedule_time = datetime.fromisoformat(msg["schedule_time"])
            if schedule_time.tzinfo is not None:
                schedule_time = schedule_time.replace(tzinfo=None)
        except Exception as e:
            logger.error(f"Bad schedule_time for msg_id={msg.get('id')}: {e}")
            continue

        if schedule_time <= now:
            schedule_time = now + timedelta(seconds=5)
            missed += 1

        import json as _json
        reply_markup = None
        raw_markup = msg.get("reply_markup_json")
        if raw_markup:
            try:
                from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                markup_data = _json.loads(raw_markup)
                keyboard = [
                    [InlineKeyboardButton(btn["text"],
                                          callback_data=btn.get("callback_data"),
                                          url=btn.get("url"))
                     for btn in row]
                    for row in markup_data.get("inline_keyboard", [])
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
            except Exception as e:
                logger.warning(f"Could not restore reply_markup for msg_id={msg.get('id')}: {e}")

        scheduler.schedule_message(
            msg["id"],
            msg["target_type"],
            msg["target_id"],
            msg.get("message_text", ""),
            schedule_time,
            media_type=msg.get("media_type"),
            media_file_id=msg.get("media_file_id"),
            media_caption=msg.get("media_caption"),
            reply_markup=reply_markup,
        )
        restored += 1

    logger.info(
        f"Rescheduled {restored} pending message(s) on startup "
        f"({missed} were past due and will fire shortly)."
    )
