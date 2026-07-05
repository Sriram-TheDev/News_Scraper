# Deployment Guide

## Prerequisites

Before deploying, ensure you have:
- GitHub account with a private repository
- Render account (free tier)
- Supabase project created
- All API keys obtained

## Step 1: Database Setup

1. Go to your Supabase project's SQL Editor
2. Copy and execute the entire contents of `schema.sql`
3. Verify tables were created: `bot_settings`, `url_history`, `digest_buffer`
4. Verify RLS is enabled on all tables

## Step 2: GitHub Setup

1. Create a private GitHub repository
2. Push this codebase to the repository:
   ```bash
   git init
   git add .
   git commit -m "Initial commit: JIT News Vault"
   git remote add origin <your-repo-url>
   git push -u origin main
   ```

## Step 3: Render Deployment

1. Go to [Render.com](https://render.com) and log in
2. Click "New +" → "Web Service"
3. Connect your GitHub repository
4. Configure the web service:
   - **Name**: jit-news-vault
   - **Region**: Oregon (or closest to you)
   - **Branch**: main
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Add Environment Variables (from `.env.example`):
   - `SUPABASE_URL` - Your Supabase project URL
   - `SUPABASE_SERVICE_KEY` - Your Supabase service_role key (NOT anon key)
   - `FIRECRAWL_API_KEY` - Your Firecrawl API key
   - `GEMINI_API_KEY` - Your Gemini API key
   - `TELEGRAM_BOT_TOKEN` - From BotFather
   - `TELEGRAM_SECRET_TOKEN` - Create a random string for webhook verification
   - `ADMIN_CHAT_ID` - Your Telegram user ID (get from @userinfobot)
   - `CRON_SECRET_TOKEN` - Create a random string for cron verification
6. Click "Deploy Web Service"
7. Wait for deployment to complete (2-3 minutes)
8. Copy the Render URL (e.g., `https://jit-news-vault.onrender.com`)

## Step 4: Telegram Webhook Setup

1. Get your Render URL from the previous step
2. Set the webhook via Telegram API:
   ```bash
   curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
   -d "url=https://<YOUR_RENDER_URL>/webhook" \
   -d "secret_token=<YOUR_TELEGRAM_SECRET_TOKEN>"
   ```
3. Verify webhook is set:
   ```bash
   curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
   ```

## Step 5: Cron-job.org Setup

1. Go to [Cron-job.org](https://cron-job.org) and log in
2. Create a new cron job:
   - **Title**: JIT News Digest
   - **URL**: `https://<YOUR_RENDER_URL>/cron-digest`
   - **Execution schedule**: Set to 15 minutes before your desired delivery time
   - **Method**: POST
   - **Headers**: Add header `X-Cron-Secret-Token: <YOUR_CRON_SECRET_TOKEN>`
3. Save and enable the cron job

## Step 6: Testing

1. Open Telegram and start a chat with your bot
2. Send `/start` - you should see the welcome message
3. Send `/status` - you should see current settings
4. Send `/addtag tech` - should confirm tag added
5. Send `/addsource https://example.com` - should confirm source added
6. Wait for the cron job to trigger, or manually test the `/cron-digest` endpoint

## Troubleshooting

### Webhook not receiving updates
- Verify the webhook URL is correct
- Check that `TELEGRAM_SECRET_TOKEN` matches in both Render and the webhook setup
- Check Render logs for errors

### Cron job failing
- Verify `CRON_SECRET_TOKEN` matches in both Render and cron-job.org
- Check Render logs for the `/cron-digest` endpoint
- Ensure Supabase is accessible from Render

### Database errors
- Verify `SUPABASE_SERVICE_KEY` is the service_role key, not anon key
- Check that RLS policies are enabled
- Verify the schema was executed correctly

### LLM errors
- Verify `GEMINI_API_KEY` is valid
- Check Gemini API quota limits

### Telegraph errors
- Telegraph may rate limit - if errors persist, add delays between page creations
