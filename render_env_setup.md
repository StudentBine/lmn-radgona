# Render Environment Variables Setup

## Required Environment Variables for your Render deployment:

### 1. Database Configuration
```
DATABASE_URL=your_neon_postgres_connection_string
```

### 2. Flask Configuration
```
SECRET_KEY=your_secure_random_secret_key_here
FLASK_ENV=production
```

### 3. Scraping Configuration (New - IMPORTANT)
```
SCRAPER_DEBUG=false
SCRAPER_MAX_WORKERS=2
ENABLE_SCRAPING=false
```

**Note**: Set ENABLE_SCRAPING=false initially to avoid 415 errors and timeouts. The app will use cached data.

### 4. Optional: Redis Cache (if using Redis)
```
REDIS_URL=redis://your_redis_instance_url
```

## How to add these to Render:

1. Go to your Render dashboard
2. Select your web service
3. Go to "Environment" tab
4. Add each variable with its value
5. Click "Save Changes" - this will trigger a redeploy

## Cloudflare Bypass Strategies Implemented:

1. **Multiple User Agents**: Rotates between desktop, mobile, and older browsers
2. **Progressive Retry**: 5 attempts with different headers and delays
3. **Mobile Fallback**: Uses mobile user agents that are often less scrutinized
4. **Graceful Degradation**: Falls back to cached data when scraping fails
5. **Production Mode**: Can disable scraping entirely with ENABLE_SCRAPING=false

## Testing the fixes:

After deployment, you can test:
- `/admin/force-debug-test` - Tests scraping with debug output
- `/admin/mobile-fallback-test` - Tests mobile user agent
- `/league/liga_a/leaderboard?force=true` - Forces fresh data fetch
- `/admin/clear-cache/liga_a` - Clears cache to test scraping

## Fixes Applied:

1. **HTTP 415 Error**: Added Accept-Charset headers and simplified retry headers
2. **Worker Timeouts**: Added 10s timeout for web requests, 15s for background tasks
3. **Graceful Degradation**: App now defaults to cached data when scraping fails
4. **Production Safety**: Scraping disabled by default in production environment

## If Issues Persist:

1. **First**: Keep `ENABLE_SCRAPING=false` - app works entirely on cached data
2. **Test scraping**: Use `/admin/toggle-scraping` to enable temporarily
3. **Monitor**: Use `/admin/status` to check app health
4. **Long-term**: Consider proxy services or API access from site owner