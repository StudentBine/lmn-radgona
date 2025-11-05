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

### 3. Scraping Configuration (New)
```
SCRAPER_DEBUG=false
SCRAPER_MAX_WORKERS=2
ENABLE_SCRAPING=true
```

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

## If Cloudflare continues blocking:

Set `ENABLE_SCRAPING=false` to rely entirely on cached data until you can:
1. Implement proxy rotation
2. Add CAPTCHA solving service
3. Use a different hosting provider with different IP ranges
4. Contact the website owner for API access