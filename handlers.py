import re
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ChatJoinRequestHandler
from config import Config
from database import db
from ai_handler import ai_handler
from qr_handler import generate_qr_code
from keyboards import *
from scheduler import scheduler
from datetime import datetime, timedelta, timezone

USER_CHANNEL_ADD = 999

# Conversation states
(AI_CHAT, SCHEDULE_TARGET, SCHEDULE_TIME, SCHEDULE_MSG, SCHEDULE_MEDIA, 
 SCHEDULE_CAPTION, QR_INPUT, ADMIN_ADD, CHANNEL_ADD, AI_LIMIT, 
 UPDATE_TITLE, UPDATE_MSG, SCHEDULE_POLL_Q, SCHEDULE_POLL_OPTS,
 SCHEDULE_CONTACT, SCHEDULE_LOCATION,
 SET_DEFAULT_AI_LIMIT, SET_USER_AI_LIMIT, UPDATE_INVITE_LINK, SCHEDULE_DATE, SCHEDULE_AMPM) = range(21)

# ========== HELPER FUNCTIONS ==========

async def join_request(update, context):

    req = update.chat_join_request

    user_id = req.from_user.id
    channel_id = req.chat.id

    print(
        f"JOIN REQUEST: {user_id} -> {channel_id}"
    )

    db.save_join_request(
        user_id,
        channel_id
    )

async def is_user_joined_channels(user_id, bot):

    channels = db.get_all_channels()
    not_joined = []

    for ch in channels:

        channel_id = ch["channel_id"]

        # Already sent request
        if db.has_join_request(
            user_id,
            channel_id
        ):
            continue

        try:

            member = await bot.get_chat_member(
                channel_id,
                user_id
            )

            if member.status in [
                "member",
                "administrator",
                "creator"
            ]:
                continue

        except Exception:
            # Private channel mein bot member check nahi kar sakta.
            # Agar join_request already saved hai (upar check ho gaya),
            # toh yahan tak aaya hi nahi. Yahan aaya matlab genuinely
            # check nahi hua — skip karo, block mat karo.
            continue

        not_joined.append(ch)

    return not_joined

async def ensure_joined(update, context, user_id):

    if is_owner(user_id):
        return True

    not_joined = await is_user_joined_channels(
        user_id,
        context.bot
    )

    if not_joined:

        text = (
            "📢 Pehle required channels "
            "join/request karein."
        )

        keyboard = get_force_join_keyboard(
            not_joined
        )

        if update.callback_query:

            await update.callback_query.message.reply_text(
                text,
                reply_markup=keyboard
            )

        else:

            await update.message.reply_text(
                text,
                reply_markup=keyboard
            )

        return False

    return True



async def check_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = db.get_user(user.id)

    if not db_user:
        db.create_user(user.id, user.username, user.first_name)

    return db.get_user(user.id)

def is_owner(user_id):
    return user_id == Config.OWNER_ID

def is_admin(user_id):
    return db.get_admin(user_id) is not None or is_owner(user_id)

# ========== START COMMAND ==========
    
async def start(update, context):

    user = update.effective_user

    await check_user(update, context)

    if not await ensure_joined(
        update,
        context,
        user.id
    ):
        return

    welcome_text = (
        f"**Welcome {user.first_name}!**\n\n"
        "Main ek multi-feature bot hoon.\n"
        "Niche se option choose karein:"
    )

    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_menu(user.id),
        parse_mode="Markdown"
    )

# ========== SIDE MENU COMMAND ==========
async def side_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await check_user(update, context)

    text = "**Side Menu**\n\nQuick access to all features:"
    await update.message.reply_text(text, reply_markup=get_side_menu(user.id), parse_mode="Markdown")

# ========== HELP COMMAND ==========
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await check_user(update, context)

    text = "**Help Center**\n\nSelect a topic to learn more:"
    await update.message.reply_text(text, reply_markup=get_help_menu(), parse_mode="Markdown")

# ========== CALLBACK HANDLER ==========
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    # Silently ignore stale queries (bot was sleeping / HF space woke up)
    try:
        await query.answer()
    except Exception:
        return

    SKIP_JOIN_CHECK = {
        "check_join", "close", "help", "help_ai",
        "help_schedule", "help_qr", "help_updates",
        "help_admin", "help_auto_approve"
    }
    if data not in SKIP_JOIN_CHECK:
        if not await ensure_joined(update, context, user_id):
            return

    # ===== MAIN MENU =====
    if data == "main_menu":
        await query.edit_message_text(
            "**Main Menu**\n\nOption choose karein:",
            reply_markup=get_main_menu(user_id),
            parse_mode="Markdown"
        )
        
    elif data == "check_join":
        await query.edit_message_text(
            "✅ Verification Successful!",
            reply_markup=get_main_menu(user_id)
        )

    # ===== AI CHAT =====
    elif data == "ai_chat":
        context.user_data["active_feature"] = "ai"
    
        await query.edit_message_text(
            "**AI Chat**\n\nAapka sawal type karein:\n\n/menu se exit karein.",
            parse_mode="Markdown"
        )
    
        context.user_data["state"] = AI_CHAT

    # ===== SCHEDULE MESSAGE =====
    elif data == "schedule_msg":
        context.user_data["active_feature"] = "schedule"

        await query.edit_message_text("**Schedule Message**\n\nKahan bhejna hai?", reply_markup=get_schedule_type_keyboard(), parse_mode="Markdown")

    elif data.startswith("sched_") and data in ["sched_channel", "sched_group", "sched_user"]:
        target_type = data.replace("sched_", "")
        context.user_data["sched_target_type"] = target_type
        context.user_data["state"] = SCHEDULE_TARGET
        target_names = {"channel": "Channel", "group": "Group", "user": "User"}
        await query.edit_message_text(
            f"**{target_names.get(target_type, target_type)} ID bhejein:**\n\n"
            f"Examples:\n"
            f"- Channel: `-1001234567890`\n"
            f"- Group: `-1001234567890`\n"
            f"- User: `@username` ya `123456789`",
            parse_mode="Markdown"
        )

    # ===== MEDIA TYPE SELECTION =====
    elif data.startswith("media_"):
        media_type = data.replace("media_", "")
        context.user_data["sched_media_type"] = media_type if media_type != "text" else None

        if media_type == "text":
            context.user_data["state"] = SCHEDULE_MSG
            await query.edit_message_text("**Message text bhejein:**", parse_mode="Markdown")

        elif media_type == "location":
            context.user_data["state"] = SCHEDULE_LOCATION
            await query.edit_message_text(
                "**Location bhejein** (format: `latitude,longitude`)\n\n"
                "Example: `28.6139,77.2090`",
                parse_mode="Markdown"
            )

        elif media_type == "poll":
            context.user_data["state"] = SCHEDULE_POLL_Q
            await query.edit_message_text("**Poll question bhejein:**", parse_mode="Markdown")

        elif media_type == "contact":
            context.user_data["state"] = SCHEDULE_CONTACT
            await query.edit_message_text(
                "**Contact details bhejein** (format: `phone|first_name|last_name`)\n\n"
                "Example: `+919876543210|Rahul|Sharma`",
                parse_mode="Markdown"
            )

        else:
            # Photo, Video, Document, Audio, Voice, VideoNote, Animation, Sticker
            media_names = {
                "photo": "Photo", "video": "Video", "document": "Document",
                "audio": "Audio", "voice": "Voice", "video_note": "Video Note",
                "animation": "Animation", "sticker": "Sticker"
            }
            context.user_data["state"] = SCHEDULE_MEDIA
            await query.edit_message_text(
                f"{media_names.get(media_type, media_type)} **bhejein** (forward ya upload karein):\n\n"
                f"Note: Bot ko us channel/group mein admin hona chahiye agar wahan bhejna hai.",
                parse_mode="Markdown"
            )

    # ===== QR CODE =====
    elif data == "qr_code":
        context.user_data["active_feature"] = "qr"

        await query.edit_message_text("**QR Code Generator**\n\nText ya URL type karein:", parse_mode="Markdown")
        context.user_data["state"] = QR_INPUT

    # ===== AUTO APPROVE  =====
    elif data == "auto_approve_menu":
    
        text = (
            "🤖 Auto Request Approver\n\n"
            "Bot ko apne channel/group me admin banaein.\n"
            "Phir channel add karein.\n\n"
            "Join requests automatically approve hongi."
        )
    
        keyboard = [
            [
                InlineKeyboardButton(
                    "➕ Add Channel",
                    callback_data="user_add_channel"
                )
            ],
            [
                InlineKeyboardButton(
                    "📋 My Channels",
                    callback_data="user_my_channels"
                )
            ]
        ]
    
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )

    elif data == "user_add_channel":
        await query.edit_message_text(
            "Channel ID bhejein:\n\nExample:\n-1002390781736"
        )
        context.user_data["state"] = USER_CHANNEL_ADD

    elif data == "user_my_channels":
        channels = db.get_user_channels(user_id)
        if not channels:
            await query.edit_message_text(
                "📋 Aapne koi channel add nahi kiya.\n\nPehle channel add karein.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Add Channel", callback_data="user_add_channel")],
                    [InlineKeyboardButton("🔙 Back", callback_data="auto_approve_menu")]
                ])
            )
        else:
            buttons = []
            for ch in channels:
                status = "✅ Auto ON" if ch.get("auto_approve") else "❌ Auto OFF"
                buttons.append([InlineKeyboardButton(
                    f"{ch['channel_name']} ({status})",
                    callback_data=f"user_ch_toggle_{ch['channel_id']}"
                )])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="auto_approve_menu")])
            await query.edit_message_text(
                "📋 **Aapke Channels:**\n\nClick to toggle auto-approve.",
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode="Markdown"
            )

    elif data.startswith("user_ch_toggle_"):
        ch_id = int(data.replace("user_ch_toggle_", ""))
        ch = db.get_user_channel(ch_id)
        if ch and ch.get("user_id") == user_id:
            new_state = not ch.get("auto_approve", False)
            db.toggle_auto_approve(ch_id, new_state)
            status = "✅ Enabled" if new_state else "❌ Disabled"
            await query.answer(f"Auto-Approve {status}!", show_alert=True)
            # Refresh the list
            channels = db.get_user_channels(user_id)
            buttons = []
            for c in channels:
                s = "✅ Auto ON" if c.get("auto_approve") else "❌ Auto OFF"
                buttons.append([InlineKeyboardButton(
                    f"{c['channel_name']} ({s})",
                    callback_data=f"user_ch_toggle_{c['channel_id']}"
                )])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="auto_approve_menu")])
            await query.edit_message_text(
                "📋 **Aapke Channels:**",
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode="Markdown"
            )
        else:
            await query.answer("❌ Channel nahi mila.", show_alert=True)

    # ===== BOT UPDATES =====
    elif data == "bot_updates":
        updates = db.get_all_updates()
        if not updates:
            text = "**Koi update nahi hai abhi.**"
        else:
            text = "**Bot Updates:**\n\n"
            for up in updates[:5]:
                text += f"**{up['title']}**\n{up['message']}\n\n"
        await query.edit_message_text(text, reply_markup=get_main_menu(user_id), parse_mode="Markdown")

    # ===== MY SCHEDULED MESSAGES =====
    elif data == "my_scheduled":
        msgs = db.get_user_scheduled_messages(user_id)
        if not msgs:
            await query.edit_message_text("**Aapke koi scheduled messages nahi hain.**", reply_markup=get_main_menu(user_id), parse_mode="Markdown")
        else:
            await query.edit_message_text("**Your Scheduled Messages:**", reply_markup=get_scheduled_list_keyboard(msgs), parse_mode="Markdown")

    elif data.startswith("sched_detail_"):
        msg_id = int(data.replace("sched_detail_", ""))
        msgs = db.get_user_scheduled_messages(user_id)
        msg = next((m for m in msgs if m["id"] == msg_id), None)
        if msg:
            from keyboards import get_media_label
            icon, fmt = get_media_label(msg.get("media_type"))
            status = "⏳ Pending" if msg["status"] == "pending" else "✅ Sent" if msg["status"] == "sent" else f"❌ {msg['status']}"
            time_str = msg["schedule_time"][:16] if msg["schedule_time"] else "N/A"
            target = str(msg.get('target_type', '?')) + ' -> ' + str(msg.get('target_id', '?'))
            preview = msg.get("media_caption") or msg.get("message_text") or "—"
            if len(preview) > 80:
                preview = preview[:80] + "..."
            detail_text = (
                "**📋 Schedule Detail**\n\n"
                f"🆔 ID: `{msg_id}`\n"
                f"📁 Format: {icon} `{fmt}`\n"
                f"🎯 Target: {target}\n"
                f"🕐 Time: `{time_str}`\n"
                f"📊 Status: {status}\n"
                f"💬 Content: {preview}"
            )
        else:
            detail_text = f"**Schedule ID:** `{msg_id}`"
        await query.edit_message_text(detail_text, reply_markup=get_scheduled_detail_keyboard(msg_id), parse_mode="Markdown")

    elif data.startswith("del_sched_"):
        msg_id = int(data.replace("del_sched_", ""))
        db.delete_scheduled_message(msg_id)
        if scheduler:
            scheduler.remove_scheduled_job(msg_id)
        await query.edit_message_text("**Schedule delete ho gaya!**", reply_markup=get_main_menu(user_id), parse_mode="Markdown")

    # ===== OWNER PANEL =====
    elif data == "owner_panel":
        if not is_owner(user_id):
            await query.answer("Sirf owner access kar sakta hai!", show_alert=True)
            return
        await query.edit_message_text("**Owner Panel**", reply_markup=get_owner_panel(), parse_mode="Markdown")

    elif data == "add_channel":
        if not is_owner(user_id):
            return
    
        await query.edit_message_text(
            "**Channel ID bhejein**\n\n"
            "Example:\n"
            "`-1002390781736`\n\n"
            "Bot ko channel mein admin banaein.",
            parse_mode="Markdown"
        )
    
        context.user_data["state"] = "channel_add_id"

    elif data == "add_admin":
        if not is_owner(user_id):
            return
        await query.edit_message_text("**Admin ka Telegram ID bhejein:**", parse_mode="Markdown")
        context.user_data["state"] = ADMIN_ADD

    elif data == "ai_limit_menu":
        await query.edit_message_text(
            "🤖 **AI Limit Management**\n\nChoose an option:",
            reply_markup=get_ai_limit_keybord()
        )


    elif data == "set_user_ai_limit":
        await query.edit_message_text(
            "**Specific user ka AI limit set karein**\n\n"
            "Format:\n"
            "`user_id|limit`\n\n"
            "Example:\n"
            "`123456789|100`",
            parse_mode="Markdown"
        )
    
        context.user_data["state"] = SET_USER_AI_LIMIT
    
    elif data == "set_admin_ai_limit":
        await query.edit_message_text(
            "**Sabhi users ka default AI limit set karein**\n\n"
            "Format:\n"
            "`limit`\n\n"
            "Example:\n"
            "`20`",
            parse_mode="Markdown"
        )
    
        context.user_data["state"] = SET_DEFAULT_AI_LIMIT


    elif data == "channel_list":
        if not is_owner(user_id):
            return
        channels = db.get_all_channels()
        if not channels:
            await query.edit_message_text("**Koi channel add nahi hai.**", reply_markup=get_owner_panel(), parse_mode="Markdown")
        else:
            await query.edit_message_text("**Channel List:**", reply_markup=get_channel_list_keyboard(channels), parse_mode="Markdown")

    elif data.startswith("ch_detail_"):
        if not is_owner(user_id):
            return
        ch_id = int(data.replace("ch_detail_", ""))
        ch = db.get_channel(ch_id)
        if ch:
            text = f"**{ch['channel_name']}**\nAuto-Approve: {'ON' if ch['auto_approve'] else 'OFF'}"
            await query.edit_message_text(text, reply_markup=get_channel_detail_keyboard(ch_id, ch["auto_approve"]), parse_mode="Markdown")

    elif data.startswith("toggle_approve_"):
        if not is_owner(user_id):
            return
        ch_id = int(data.replace("toggle_approve_", ""))
        ch = db.get_channel(ch_id)
        if ch:
            new_status = not ch["auto_approve"]
            db.update_channel_auto_approve(ch_id, new_status)
            await query.edit_message_text(f"Auto-Approve {'enabled' if new_status else 'disabled'}!", reply_markup=get_channel_detail_keyboard(ch_id, new_status), parse_mode="Markdown")

    elif data.startswith("update_link_"):
        if not is_owner(user_id):
            return
        ch_id = int(data.replace("update_link_", ""))
        context.user_data["update_link_channel_id"] = ch_id
        context.user_data["state"] = UPDATE_INVITE_LINK
        await query.edit_message_text(
            "**Naya Invite Link bhejein:**\n\nExample:\n`https://t.me/+abc123xyz`",
            parse_mode="Markdown"
        )

    elif data.startswith("remove_ch_"):
        if not is_owner(user_id):
            return
        ch_id = int(data.replace("remove_ch_", ""))
        db.remove_channel(ch_id)
        await query.edit_message_text("**Channel remove ho gaya!**", reply_markup=get_owner_panel(), parse_mode="Markdown")

    elif data == "admin_list":
        if not is_owner(user_id):
            return
        admins = db.get_all_admins()
        if not admins:
            await query.edit_message_text("**Koi admin nahi hai.**", reply_markup=get_owner_panel(), parse_mode="Markdown")
        else:
            await query.edit_message_text("**Admin List:**", reply_markup=get_admin_list_keyboard(admins), parse_mode="Markdown")

    elif data.startswith("admin_detail_"):
        if not is_owner(user_id):
            return
        admin_id = int(data.replace("admin_detail_", ""))
        await query.edit_message_text(f"**Admin ID:** `{admin_id}`", reply_markup=get_admin_detail_keyboard(admin_id), parse_mode="Markdown")

    elif data.startswith("remove_admin_"):
        if not is_owner(user_id):
            return
        admin_id = int(data.replace("remove_admin_", ""))
        db.remove_admin(admin_id)
        await query.edit_message_text("**Admin remove ho gaya!**", reply_markup=get_owner_panel(), parse_mode="Markdown")

    elif data == "post_update":
        if not is_owner(user_id):
            return
        await query.edit_message_text("**Update Title bhejein:**", parse_mode="Markdown")
        context.user_data["state"] = UPDATE_TITLE

    elif data == "manage_users":
        if not is_admin(user_id):
            return
        users = db.get_all_users()
        text = f"**Total Users:** {len(users)}\n\n"
        for u in users[:20]:
            text += f"- `{u['user_id']}` - {u.get('first_name', 'N/A')}\n"
        await query.edit_message_text(text, reply_markup=get_main_menu(user_id), parse_mode="Markdown")

    elif data == "stats":
        if not is_owner(user_id):
            return
        users = db.get_all_users()
        channels = db.get_all_channels()
        admins = db.get_all_admins()
        text = f"**Bot Stats**\n\nTotal Users: {len(users)}\nTotal Channels: {len(channels)}\nTotal Admins: {len(admins)}"
        await query.edit_message_text(text, reply_markup=get_owner_panel(), parse_mode="Markdown")

    # ===== HELP SECTION =====
    elif data == "help":
        text = "**Help Center**\n\nSelect a topic to learn more:"
        await query.edit_message_text(text, reply_markup=get_help_menu(), parse_mode="Markdown")

    elif data == "help_ai":
        text = (
            "**AI Chat Help**\n\n"
            "1. Main Menu se **AI Chat** select karein\n"
            "2. Aapka sawal type karein\n"
            "3. Groq AI jawab dega\n\n"
            "**Daily Limit:** Owner ne set kiya hua limit har din apply hota hai\n"
            "Aapke remaining requests har response ke saath dikhenge\n\n"
            "**Example:** `What is Python?` ya `Mujhe Python ke baare mein batao`"
        )
        await query.edit_message_text(text, reply_markup=get_help_menu(), parse_mode="Markdown")

    elif data == "help_schedule":
        text = (
            "**Schedule Message Help**\n\n"
            "**Steps:**\n"
            "1. **Schedule Message** select karein\n"
            "2. Target choose karein: Channel / Group / User\n"
            "3. Target ID bhejein (e.g., `-1001234567890` ya `@username`)\n"
            "4. Media type select karein (Text, Photo, Video, etc.)\n"
            "5. Media upload karein ya text type karein\n"
            "6. Caption add karein (optional, `/skip` se skip)\n"
            "7. Time bhejein: `YYYY-MM-DD HH:MM`\n\n"
            "**Supported Media:**\n"
            "Text | Photo | Video | Document | Audio\n"
            "Voice | Video Note | GIF | Sticker\n"
            "Location | Poll | Contact\n\n"
            "**Time Format Examples:**\n"
            "- `2026-06-20 14:30` (20 June 2026, 2:30 PM)\n"
            "- `2026-06-20 09:00` (20 June 2026, 9:00 AM)"
        )
        await query.edit_message_text(text, reply_markup=get_help_menu(), parse_mode="Markdown")


    elif data == "help_auto_approve":
        text = (
            "**Auto Approve Help**\n\n"
            "**What is Auto Approve?**\n"
            "- Bot join requests automatically approve karta hai\n"
            "- Private Channels aur Groups support karta hai\n"
            "- Multiple channels add kar sakte hain\n\n"
            "**How to Setup:**\n"
            "- Bot ko Channel/Group mein Admin banaein\n"
            "- Invite Users permission enable karein\n"
            "- Auto Approve Requests menu open karein\n"
            "- Add Channel par click karein\n"
            "- Channel ID bhejein\n\n"
            "**Available Features:**\n"
            "- Channel add/remove kar sakte hain\n"
            "- Auto Approve ON/OFF kar sakte hain\n"
            "- Multiple channels manage kar sakte hain\n"
            "- Join requests automatically approve hongi\n\n"
            "**Requirements:**\n"
            "- Bot admin hona chahiye\n"
            "- Join Requests enabled honi chahiye\n"
            "- Correct Channel ID use karein\n\n"
            "**Important Notes:**\n"
            "- Public aur Private dono channels support hain\n"
            "- Owner aur Admins force join bypass karte hain\n"
            "- Bot offline hone par requests approve nahi hongi\n\n"
            "**Commands:**\n"
            "- `/start` - Main Menu\n"
            "- `/sidemenu` - Side Menu\n"
            "- `/help` - Help Center"
        )
        await query.edit_message_text(text, reply_markup=get_help_menu(), parse_mode="Markdown")


    elif data == "help_qr":
        text = (
            "**QR Code Help**\n\n"
            "1. **QR Code** select karein\n"
            "2. Koi bhi text, URL, ya phone number type karein\n"
            "3. Bot automatically QR code generate karke bhejega\n\n"
            "**Examples:**\n"
            "- `https://google.com`\n"
            "- `Hello World`\n"
            "- `+919876543210`\n"
            "- WiFi format: `WIFI:T:WPA;S:NetworkName;P:Password;;`"
        )
        await query.edit_message_text(text, reply_markup=get_help_menu(), parse_mode="Markdown")

    elif data == "help_updates":
        text = (
            "**Bot Updates Help**\n\n"
            "- Owner bot ke latest updates yahan post karta hai\n"
            "- Naye features, announcements, aur news yahan milenge\n"
            "- **Bot Updates** button se check karein\n\n"
            "Sirf owner hi updates post kar sakta hai"
        )
        await query.edit_message_text(text, reply_markup=get_help_menu(), parse_mode="Markdown")

    elif data == "help_admin":
        text = (
            "**Admin/Owner Help**\n\n"
            "**Admin Features:**\n"
            "- Users list dekh sakta hai\n"
            "- Scheduled messages manage kar sakta hai\n"
            "- Channel join check bypass hota hai\n\n"
            "**Owner Features (Admin + Extra):**\n"
            "- Channels add/remove kar sakta hai\n"
            "- Admins add/remove kar sakta hai\n"
            "- AI daily limit set kar sakta hai\n"
            "- Bot updates post kar sakta hai\n"
            "- Statistics dekh sakta hai\n"
            "- Auto-approve toggle kar sakta hai\n\n"
            "**Commands:**\n"
            "- `/start` - Bot start + Main Menu\n"
            "- `/sidemenu` - Side Menu open\n"
            "- `/help` - Help Center"
        )
        await query.edit_message_text(text, reply_markup=get_help_menu(), parse_mode="Markdown")

    elif data == "close":
        await query.delete_message()


async def _finalize_schedule(update, context, user, schedule_time_utc, ist_display):
    """Save to DB and schedule the message after time is confirmed."""
    target_type = context.user_data.get("sched_target_type")
    target_id_raw = context.user_data.get("sched_target_id")
    media_type = context.user_data.get("sched_media_type")
    media_file_id = context.user_data.get("sched_media_file_id")
    media_caption = context.user_data.get("sched_media_caption")
    message_text = context.user_data.get("sched_message_text", "")

    try:
        if target_id_raw.startswith("@"):
            chat = await context.bot.get_chat(target_id_raw)
            target_id = chat.id
        else:
            target_id = int(target_id_raw)
    except Exception:
        await update.message.reply_text("**Invalid target ID/username!**", parse_mode="Markdown")
        context.user_data.clear()
        return

    now_utc = datetime.utcnow()
    if schedule_time_utc <= now_utc:
        await update.message.reply_text("\u274c **Past time nahi dal sakte!** Dobara /start karein.", parse_mode="Markdown")
        context.user_data.clear()
        return

    msg_data = db.add_scheduled_message(
        user.id, target_type, target_id, message_text, schedule_time_utc,
        media_type=media_type, media_file_id=media_file_id, media_caption=media_caption
    )

    if msg_data and scheduler:
        scheduler.schedule_message(
            msg_data["id"], target_type, target_id, message_text, schedule_time_utc,
            media_type=media_type, media_file_id=media_file_id, media_caption=media_caption
        )

    MEDIA_NAMES = {
        "photo": "\U0001f4f7 Photo", "video": "\U0001f3ac Video",
        "document": "\U0001f4c4 Document", "audio": "\U0001f3b5 Audio",
        "voice": "\U0001f3a4 Voice", "video_note": "\U0001f39e Video Note",
        "animation": "\U0001f3ad Animation/GIF", "sticker": "\U0001f3f7 Sticker",
        "location": "\U0001f4cd Location", "poll": "\U0001f4ca Poll",
        "contact": "\U0001f464 Contact",
    }
    media_icon = MEDIA_NAMES.get(media_type, "\U0001f4dd Text")
    await update.message.reply_text(
        f"\u2705 **Message Scheduled!**\n\n"
        f"Type: {media_icon}\n"
        f"Target: {target_type}\n"
        f"\U0001f550 Time (IST): {ist_display}\n"
        f"Schedule ID: `{msg_data['id'] if msg_data else 'N/A'}`",
        reply_markup=get_main_menu(user.id),
        parse_mode="Markdown"
    )
    context.user_data.clear()

# ========== MESSAGE HANDLER ==========
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Guard: ignore non-user messages (channel posts, etc.)
    if not update.message or not update.effective_user:
        return

    user = update.effective_user
    text = update.message.text  # None for media messages — checked below per-type
    state = context.user_data.get("state")

    # Handle media messages (photo, video, document, etc.)
    if update.message.photo and state == SCHEDULE_MEDIA:
        file_id = update.message.photo[-1].file_id
        context.user_data["sched_media_file_id"] = file_id
        context.user_data["state"] = SCHEDULE_CAPTION
        await update.message.reply_text("**Caption bhejein** (ya /skip karein):", parse_mode="Markdown")
        return

    elif update.message.video and state == SCHEDULE_MEDIA:
        file_id = update.message.video.file_id
        context.user_data["sched_media_file_id"] = file_id
        context.user_data["state"] = SCHEDULE_CAPTION
        await update.message.reply_text("**Caption bhejein** (ya /skip karein):", parse_mode="Markdown")
        return

    elif update.message.document and state == SCHEDULE_MEDIA:
        file_id = update.message.document.file_id
        context.user_data["sched_media_file_id"] = file_id
        context.user_data["state"] = SCHEDULE_CAPTION
        await update.message.reply_text("**Caption bhejein** (ya /skip karein):", parse_mode="Markdown")
        return

    elif update.message.audio and state == SCHEDULE_MEDIA:
        file_id = update.message.audio.file_id
        context.user_data["sched_media_file_id"] = file_id
        context.user_data["state"] = SCHEDULE_CAPTION
        await update.message.reply_text("**Caption bhejein** (ya /skip karein):", parse_mode="Markdown")
        return

    elif update.message.voice and state == SCHEDULE_MEDIA:
        file_id = update.message.voice.file_id
        context.user_data["sched_media_file_id"] = file_id
        context.user_data["state"] = SCHEDULE_CAPTION
        await update.message.reply_text("**Caption bhejein** (ya /skip karein):", parse_mode="Markdown")
        return

    elif update.message.video_note and state == SCHEDULE_MEDIA:
        file_id = update.message.video_note.file_id
        context.user_data["sched_media_file_id"] = file_id
        context.user_data["state"] = SCHEDULE_DATE
        await update.message.reply_text("\U0001f4c5 **Date bhejein:**\n\nFormat: `DD-MM-YYYY`\nExample: `25-12-2026`", parse_mode="Markdown")
        return

    elif update.message.animation and state == SCHEDULE_MEDIA:
        file_id = update.message.animation.file_id
        context.user_data["sched_media_file_id"] = file_id
        context.user_data["state"] = SCHEDULE_CAPTION
        await update.message.reply_text("**Caption bhejein** (ya /skip karein):", parse_mode="Markdown")
        return

    elif update.message.sticker and state == SCHEDULE_MEDIA:
        file_id = update.message.sticker.file_id
        context.user_data["sched_media_file_id"] = file_id
        context.user_data["state"] = SCHEDULE_DATE
        await update.message.reply_text("\U0001f4c5 **Date bhejein:**\n\nFormat: `DD-MM-YYYY`\nExample: `25-12-2026`", parse_mode="Markdown")
        return

    # Handle text messages — if no text and state doesn't need text, ignore
    if not text:
        if state not in (AI_CHAT, SCHEDULE_TARGET, SCHEDULE_TIME, SCHEDULE_MSG,
                         SCHEDULE_CAPTION, QR_INPUT, ADMIN_ADD, CHANNEL_ADD,
                         AI_LIMIT, UPDATE_TITLE, UPDATE_MSG, SCHEDULE_POLL_Q,
                         SCHEDULE_POLL_OPTS, SCHEDULE_CONTACT, SCHEDULE_LOCATION,
                         SET_DEFAULT_AI_LIMIT, SET_USER_AI_LIMIT,
                         SCHEDULE_DATE, SCHEDULE_AMPM,
                         "channel_add_id", "channel_add_link"):
            return
        # Still no text but state expects it — ask again
        await update.message.reply_text("❌ Text bhejein, media nahi.")
        return

    if state == AI_CHAT:
        await update.message.reply_text("**Soche raha hoon...**", parse_mode="Markdown")
        response, msg = ai_handler.get_ai_response(user.id, text)
        if response:
            await update.message.reply_text(f"**AI Response:**\n\n{response}\n\n{msg}", parse_mode="Markdown")
        else:
            await update.message.reply_text(msg, parse_mode="Markdown")
        

    elif state == SCHEDULE_TARGET:
        context.user_data["sched_target_id"] = text
        # Show media type selection
        await update.message.reply_text(
            "**Media type choose karein:**",
            reply_markup=get_media_type_keyboard()
        )
        context.user_data["state"] = None  # Will be set by callback

    elif state == SCHEDULE_DATE:
        # Step 1: User date bhejta hai DD-MM-YYYY format mein
        try:
            date_obj = datetime.strptime(text.strip(), "%d-%m-%Y").date()
            context.user_data["sched_date"] = date_obj
            context.user_data["state"] = SCHEDULE_TIME
            await update.message.reply_text(
                "🕐 **Time bhejein:**\n\nFormat: `HH:MM` (24-hour)\n"
                "Ya 12-hour: `HH:MM AM` ya `HH:MM PM`\n\n"
                "Examples:\n"
                "`14:30` → 2:30 PM IST\n"
                "`09:00 AM` → 9:00 AM IST\n"
                "`10:30 PM` → 10:30 PM IST",
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text(
                "❌ **Invalid date!**\n\nFormat: `DD-MM-YYYY`\nExample: `25-12-2026`",
                parse_mode="Markdown"
            )

    elif state == SCHEDULE_TIME:
        # Step 2: User time bhejta hai — 24hr ya 12hr AM/PM
        try:
            time_text = text.strip().upper()
            IST = timezone(timedelta(hours=5, minutes=30))

            if "AM" in time_text or "PM" in time_text:
                # 12-hour format: "10:30 PM" or "09:00 AM"
                time_obj = datetime.strptime(time_text, "%I:%M %p").time()
            else:
                # 24-hour format: "14:30"
                time_obj = datetime.strptime(time_text, "%H:%M").time()

            date_obj = context.user_data.get("sched_date")
            if not date_obj:
                await update.message.reply_text("❌ Date nahi mila. /start se dobara karein.")
                context.user_data.clear()
                return

            # Combine date + time as IST
            ist_naive = datetime.combine(date_obj, time_obj)
            ist_display = ist_naive.strftime("%d-%m-%Y %I:%M %p") + " IST"

            # Convert IST -> UTC naive for DB and APScheduler
            ist_aware = ist_naive.replace(tzinfo=IST)
            schedule_time_utc = ist_aware.astimezone(timezone.utc).replace(tzinfo=None)

            await _finalize_schedule(update, context, user, schedule_time_utc, ist_display)

        except ValueError:
            await update.message.reply_text(
                "❌ **Invalid time!**\n\n"
                "24-hour format: `14:30`\n"
                "12-hour format: `02:30 PM` ya `09:00 AM`",
                parse_mode="Markdown"
            )

    elif state == SCHEDULE_MSG:
        context.user_data["sched_message_text"] = text
        context.user_data["state"] = SCHEDULE_DATE
        await update.message.reply_text("\U0001f4c5 **Date bhejein:**\n\nFormat: `DD-MM-YYYY`\nExample: `25-12-2026`", parse_mode="Markdown")

    elif state == SCHEDULE_CAPTION:
        context.user_data["sched_media_caption"] = text
        context.user_data["state"] = SCHEDULE_DATE
        await update.message.reply_text("\U0001f4c5 **Date bhejein:**\n\nFormat: `DD-MM-YYYY`\nExample: `25-12-2026`", parse_mode="Markdown")

    elif state == SCHEDULE_LOCATION:
        try:
            parts = text.split(",")
            lat = float(parts[0].strip())
            lng = float(parts[1].strip())
            context.user_data["sched_media_type"] = "location"
            context.user_data["sched_media_file_id"] = f"{lat},{lng}"
            context.user_data["state"] = SCHEDULE_DATE
            await update.message.reply_text("\U0001f4c5 **Date bhejein:**\n\nFormat: `DD-MM-YYYY`\nExample: `25-12-2026`", parse_mode="Markdown")
        except:
            await update.message.reply_text("**Galat format!** Use: `latitude,longitude`\nExample: `28.6139,77.2090`", parse_mode="Markdown")

    elif state == SCHEDULE_POLL_Q:
        context.user_data["poll_question"] = text
        context.user_data["state"] = SCHEDULE_POLL_OPTS
        await update.message.reply_text(
            "**Poll options bhejein** (comma separated):\n\n"
            "Example: `Option 1, Option 2, Option 3`",
            parse_mode="Markdown"
        )

    elif state == SCHEDULE_POLL_OPTS:
        try:
            options = [opt.strip() for opt in text.split(",")]
            poll_data = {
                "question": context.user_data.get("poll_question", "Poll"),
                "options": options,
                "is_anonymous": True,
                "allows_multiple_answers": False
            }
            context.user_data["sched_media_type"] = "poll"
            context.user_data["sched_message_text"] = json.dumps(poll_data)
            context.user_data["state"] = SCHEDULE_DATE
            await update.message.reply_text("\U0001f4c5 **Date bhejein:**\n\nFormat: `DD-MM-YYYY`\nExample: `25-12-2026`", parse_mode="Markdown")
        except:
            await update.message.reply_text("**Galat format!** Use comma separated options.", parse_mode="Markdown")

    elif state == SCHEDULE_CONTACT:
        try:
            parts = text.split("|")
            phone = parts[0].strip()
            first_name = parts[1].strip() if len(parts) > 1 else "Contact"
            last_name = parts[2].strip() if len(parts) > 2 else ""
            context.user_data["sched_media_type"] = "contact"
            context.user_data["sched_media_file_id"] = f"{phone}|{first_name}|{last_name}"
            context.user_data["state"] = SCHEDULE_DATE
            await update.message.reply_text("\U0001f4c5 **Date bhejein:**\n\nFormat: `DD-MM-YYYY`\nExample: `25-12-2026`", parse_mode="Markdown")
        except:
            await update.message.reply_text("**Galat format!** Use: `phone|first_name|last_name`", parse_mode="Markdown")

    elif state == QR_INPUT:
        qr_bio = generate_qr_code(text)
        await update.message.reply_photo(photo=qr_bio, caption="**Aapka QR Code:**")
        await update.message.reply_text("**Main Menu:**", reply_markup=get_main_menu(user.id), parse_mode="Markdown")
        context.user_data["state"] = None
    
    elif state == "channel_add_id" and is_owner(user.id):
    
        try:
            ch_id = int(text.strip())
    
            context.user_data["channel_id"] = ch_id
    
            await update.message.reply_text(
                "**Ab Invite Link bhejein**\n\n"
                "Example:\n"
                "`https://t.me/+abc123xyz`",
                parse_mode="Markdown"
            )
    
            context.user_data["state"] = "channel_add_link"
    
        except:
            await update.message.reply_text(
                "❌ Invalid Channel ID"
            )
    
    
    elif state == "channel_add_link" and is_owner(user.id):
    
        try:
            invite_link = text.strip()
    
            ch_id = context.user_data.get("channel_id")
    
            
    
            db.add_channel(
                ch_id,
                f"Channel {ch_id}",
                invite_link,
                user.id
            )
                
            await update.message.reply_text(
                f"✅ Channel Added:\n{ch_id}",
                reply_markup=get_owner_panel()
            )
    
        except Exception as e:
            await update.message.reply_text(
                f"❌ Error:\n{e}",
                reply_markup=get_owner_panel()
            )
    
        context.user_data.pop("channel_id", None)
        context.user_data["state"] = None
    


    elif state == USER_CHANNEL_ADD:
    
        try:
            channel_id = int(text)
    
            chat = await context.bot.get_chat(
                channel_id
            )
    
            me = await context.bot.get_me()
    
            member = await context.bot.get_chat_member(
                channel_id,
                me.id
            )
    
            if member.status not in [
                "administrator",
                "creator"
            ]:
    
                await update.message.reply_text(
                    "❌ Bot admin nahi hai."
                )
    
                return
    
            db.add_user_channel(
                update.effective_user.id,
                channel_id,
                chat.title
            )
    
            await update.message.reply_text(
                f"✅ Added:\n{chat.title}"
            )
    
        except Exception as e:
    
            await update.message.reply_text(
                f"❌ Error:\n{e}"
            )
    
        context.user_data["state"] = None
    

    elif state == ADMIN_ADD and is_owner(user.id):
        try:
            admin_id = int(text)
            db.add_admin(admin_id, user.id)
            await update.message.reply_text(f"**Admin added:** `{admin_id}`", reply_markup=get_owner_panel(), parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"**Error:** {str(e)}", reply_markup=get_owner_panel(), parse_mode="Markdown")
        context.user_data["state"] = None


    elif state == SET_DEFAULT_AI_LIMIT:
    
        if not is_owner(user.id):
            await update.message.reply_text(
                "❌ Only owner can change AI limits."
            )
            context.user_data["state"] = None
            return
    
        limit = int(text)
    
        db.set_default_ai_limit(limit)
    
        await update.message.reply_text(
            f"✅ Default AI limit set to {limit}",
            reply_markup=get_owner_panel()
        )
    
        context.user_data["state"] = None    
        
    elif state == SET_USER_AI_LIMIT and is_owner(user.id):
        try:
            parts = text.split("|")
            target_user_id = int(parts[0].strip())
            limit = int(parts[1].strip())
            db._patch(Config.TABLE_USERS, {"ai_limit": limit}, {"user_id": f"eq.{target_user_id}"})
            await update.message.reply_text(f"**User {target_user_id} ka AI limit {limit} set ho gaya!**", reply_markup=get_owner_panel(), parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"**Error:** {str(e)}\n\nFormat: `user_id|limit`", reply_markup=get_owner_panel(), parse_mode="Markdown")
        context.user_data["state"] = None

    elif state == UPDATE_INVITE_LINK and is_owner(user.id):
        invite_link = text.strip()
        ch_id = context.user_data.get("update_link_channel_id")
        if not ch_id:
            await update.message.reply_text("❌ Error: Channel ID nahi mila. Dobara try karein.")
            context.user_data["state"] = None
            return
        if not invite_link.startswith("https://t.me/"):
            await update.message.reply_text(
                "❌ Invalid link! Format hona chahiye:\n`https://t.me/+abc123xyz`\n\nDobara bhejein:",
                parse_mode="Markdown"
            )
            return
        db.update_channel_invite_link(ch_id, invite_link)
        ch = db.get_channel(ch_id)
        await update.message.reply_text(
            f"✅ **Invite link update ho gaya!**\n\nChannel: `{ch_id}`\nNew Link: {invite_link}",
            reply_markup=get_owner_panel(),
            parse_mode="Markdown"
        )
        context.user_data.pop("update_link_channel_id", None)
        context.user_data["state"] = None

    elif state == UPDATE_TITLE and is_owner(user.id):
        context.user_data["update_title"] = text
        context.user_data["state"] = UPDATE_MSG
        await update.message.reply_text("**Update message bhejein:**", parse_mode="Markdown")

    elif state == UPDATE_MSG and is_owner(user.id):
        title = context.user_data.get("update_title", "Update")
        db.add_bot_update(title, text, user.id)
        await update.message.reply_text("**Update posted!**", reply_markup=get_owner_panel(), parse_mode="Markdown")
        context.user_data["state"] = None

    else:
        await update.message.reply_text("**Main Menu:**", reply_markup=get_main_menu(user.id), parse_mode="Markdown")

# ========== JOIN REQUEST HANDLER ==========
async def chat_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request = update.chat_join_request
    user_id = request.from_user.id
    chat_id = request.chat.id

    channel = db.get_channel(chat_id)
    if channel and channel.get("auto_approve"):
        try:
            await context.bot.approve_chat_join_request(chat_id, user_id)
            db.log_join_request(chat_id, user_id, "approved_auto")
        except Exception as e:
            print(f"Auto-approve error: {e}")


async def handle_join_request(
    update,
    context
):
    req = update.chat_join_request

    user_id = req.from_user.id
    channel_id = req.chat.id

    # Existing force join save
    db.save_join_request(
        user_id,
        channel_id
    )

    # New auto approve feature
    channel = db.get_user_channel(
        channel_id
    )

    if channel:

        if channel["auto_approve"]:

            try:

                await context.bot.approve_chat_join_request(
                    chat_id=channel_id,
                    user_id=user_id
                )

            except Exception as e:

                print(
                    "AUTO APPROVE ERROR:",
                    e
                )

async def combined_join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Single handler for ALL join requests.
    Previously two separate ChatJoinRequestHandlers were registered — PTB stops
    at the first match, so the second one never ran. This merges both.
    """
    req = update.chat_join_request
    user_id = req.from_user.id
    channel_id = req.chat.id

    # 1. Save for force-join verification
    db.save_join_request(user_id, channel_id)

    # 2. Owner-channel auto-approve
    owner_channel = db.get_channel(channel_id)
    if owner_channel and owner_channel.get("auto_approve"):
        try:
            await context.bot.approve_chat_join_request(channel_id, user_id)
            db.log_join_request(channel_id, user_id, "approved_auto")
        except Exception as e:
            print(f"Owner channel auto-approve error: {e}")
        return  # already approved, no need to check user channels

    # 3. User-channel auto-approve
    user_channel = db.get_user_channel(channel_id)
    if user_channel and user_channel.get("auto_approve"):
        try:
            await context.bot.approve_chat_join_request(chat_id=channel_id, user_id=user_id)
        except Exception as e:
            print(f"User channel auto-approve error: {e}")

async def skip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /skip command for optional steps like caption."""
    state = context.user_data.get("state")
    if state == SCHEDULE_CAPTION:
        context.user_data["sched_media_caption"] = None
        context.user_data["state"] = SCHEDULE_DATE
        await update.message.reply_text(
            "\U0001f4c5 **Date bhejein:**\n\nFormat: `DD-MM-YYYY`\nExample: `25-12-2026`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ Abhi /skip use nahi ho sakta.")

async def menu_command(update, context):
    context.user_data.clear()
    user = update.effective_user
    if not await ensure_joined(update, context, user.id):
        return
    await update.message.reply_text(
        "📋 Main Menu",
        reply_markup=get_main_menu(user.id)
    )

    