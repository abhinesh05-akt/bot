---
title: Telegram Multi-Feature Bot
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: docker
sdk_version: "20.10.0"
pinned: false
---

# 🤖 Telegram Multi-Feature Bot

## Features
- 🤖 **AI Chat** with Groq API (daily limit set by owner)
- ✅ **Auto-Approve** join requests for channels/groups
- 📅 **Message Scheduling** - Text, Photo, Video, Document, Audio, Voice, Video Note, Animation, Sticker, Location, Poll, Contact
- 📊 **QR Code Generator**
- 📢 **Channel Force Join** system
- 👤 **Owner/Admin** management panel
- 📊 **Bot Statistics**
- 📝 **Bot Updates** posting

## Bot Commands
- `/start` - Start bot and show main menu
- `/sidemenu` - Open side menu for quick access
- `/help` - Open help center

## Setup Instructions

### 1. Supabase Database Setup
Create these tables in your Supabase project using `supabase_schema.sql` file.

### 2. Environment Variables
Copy `.env.example` to `.env` and fill in your credentials:

```env
BOT_TOKEN=your_telegram_bot_token
OWNER_ID=your_telegram_user_id
GROQ_API_KEY=your_groq_api_key
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_service_key
```

### 3. Deploy on Hugging Face Spaces
1. Create new Space with **Docker** SDK
2. Upload all files
3. Set secrets in Space Settings
4. Bot will auto-start

### 4. Keep Bot Alive
Hugging Face free tier sleeps after inactivity. Use UptimeRobot or Cloudflare Worker to ping your Space URL every 5 minutes.

## Important Notes
1. Bot ko har channel mein **Admin** banaein with "Approve Users" permission
2. Channel ID format: `-1001234567890`
3. For auto-approve, enable it from Owner Panel after adding channel
4. For media scheduling, bot must be admin in target channel/group
