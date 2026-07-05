# JIT News Aggregator & Live Intelligence Reporter

A stateless, event-driven Telegram news bot with two execution lanes:
- **Scheduled Lane**: Morning Digest (cron-triggered, deduplicated, long-form)
- **On-Demand Lane**: Live Reporter (real-time, stateless search)

## Architecture

- **Render**: FastAPI application server (free tier)
- **Supabase**: PostgreSQL database (free tier)
- **Firecrawl**: Web scraping API
- **Gemini**: LLM for content synthesis
- **Telegraph**: Ad-free article pages
- **Telegram**: Bot interface
- **Cron-job.org**: Scheduled heartbeat (free)

## Setup Instructions

### 1. External Account Setup (Manual)

Create accounts and get API keys for:
- [Supabase](https://supabase.com) - Create project, get URL and service_role key
- [Render](https://render.com) - Create account for deployment
- [Telegram](https://t.me/botfather) - Create bot, get token and set webhook secret
- [Firecrawl](https://firecrawl.dev) - Get API key
- [Gemini](https://makersuite.google.com) - Get API key
- [Cron-job.org](https://cron-job.org) - Create account for scheduling

### 2. Database Setup

1. Go to your Supabase project's SQL Editor
2. Execute the SQL schema from `schema.sql`
3. Verify RLS is enabled on all tables

### 3. Local Development

1. Clone this repository
2. Copy `.env.example` to `.env` and fill in your API keys
3. Install dependencies: `pip install -r requirements.txt`
4. Run locally: `uvicorn main:app --reload`

### 4. Deployment

1. Push code to GitHub
2. Connect repository to Render
3. Add all environment variables from `.env` to Render
4. Deploy and get the Render URL
5. Set Telegram webhook: `https://api.telegram.org/bot<TOKEN>/setWebhook?url=<RENDER_URL>/webhook&secret_token=<SECRET>`
6. Configure Cron-job.org to ping `/cron-digest` with `CRON_SECRET_TOKEN` header

## Security Notes

- All secrets are server-side only
- RLS enabled on all Supabase tables
- Constant-time token comparison for webhooks
- Anti-prompt-injection engineering for LLM
- SSRF protection via HEAD request verification

See the Obsidian vault at `D:\Applications\memory\JIT-News-Vault` for complete architecture documentation.
