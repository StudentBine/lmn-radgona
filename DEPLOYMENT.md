# LMN Radgona - Deployment & Troubleshooting Guide

## 🚀 Render Deployment

### Fixed Issues:
1. **ModuleNotFoundError: 'config'** - Removed dependency on external config module
2. **Error template handling** - Added fallback for missing error.html
3. **Logging issues** - Safer logging configuration with fallbacks

### Current Configuration:
- **Start Command**: `gunicorn app_radgona:app --timeout 60`
- **Environment**: Python 3.11
- **Database**: PostgreSQL (Neon)
- **Cache**: Redis (if available), SimpleCache (fallback)

### Required Environment Variables:
```bash
DATABASE_URL=postgresql://user:pass@host/db
REDIS_URL=redis://localhost:6379/0  # Optional
FLASK_ENV=production
```

## 🔧 Troubleshooting Common Issues

### 1. 400/500 Errors in Crontab
**Symptoms**: Application works manually but fails in cron
**Solutions**:
- Check environment variables loading
- Ensure absolute paths in cron commands
- Verify database connectivity from cron context
- Check file permissions

### 2. Database Connection Issues
**Symptoms**: `psycopg2` connection errors
**Solutions**:
- Verify DATABASE_URL format
- Check network connectivity
- Validate SSL requirements
- Test connection pool settings

### 3. Cache/Redis Issues  
**Symptoms**: Cache-related errors
**Solutions**:
- Application automatically falls back to SimpleCache
- Verify REDIS_URL if using Redis
- Check Redis server availability

## 📋 Migration to Raspberry Pi

### Phase 1: System Setup
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install python3-pip python3-venv git postgresql postgresql-contrib redis-server nginx -y

# Configure PostgreSQL
sudo -u postgres createuser --interactive
sudo -u postgres createdb lmn_radgona
```

### Phase 2: Application Setup
```bash
# Clone and setup
cd /opt
sudo git clone https://github.com/StudentBine/lmn-radgona.git
cd lmn-radgona
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.local .env
# Edit .env with local database credentials
```

### Phase 3: Service Configuration
Create systemd service (`/etc/systemd/system/lmn-radgona.service`):
```ini
[Unit]
Description=LMN Radgona Flask App
After=network.target

[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=/opt/lmn-radgona
Environment=PATH=/opt/lmn-radgona/venv/bin
ExecStart=/opt/lmn-radgona/venv/bin/gunicorn --bind 127.0.0.1:5000 app_radgona:app --timeout 60 --workers 2
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### Phase 4: Nginx Configuration
```nginx
server {
    listen 80;
    server_name localhost;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static {
        alias /opt/lmn-radgona/static;
    }
}
```

### Phase 5: Cron Setup
Create wrapper script (`/opt/lmn-radgona/run_scraper.sh`):
```bash
#!/bin/bash
cd /opt/lmn-radgona
source venv/bin/activate
source .env
python3 scraper_radgona.py >> /var/log/lmn-scraper.log 2>&1
```

Add to crontab:
```bash
# Run every hour
0 * * * * /opt/lmn-radgona/run_scraper.sh
```

## 📊 Monitoring & Logs

### Log Locations:
- Application: `/var/log/lmn-radgona.log`
- Scraper: `/var/log/lmn-scraper.log`  
- Systemd: `journalctl -u lmn-radgona`
- Nginx: `/var/log/nginx/access.log`, `/var/log/nginx/error.log`

### Health Checks:
```bash
# Check service status
sudo systemctl status lmn-radgona

# Check database connectivity
sudo -u postgres psql -c "SELECT 1;" lmn_radgona

# Test application
curl http://localhost/league/liga_a/results
```

## 🔒 Security Considerations

1. **Database**: Use strong passwords, limit connections
2. **Firewall**: Configure UFW/iptables for port access
3. **SSL**: Use Let's Encrypt for HTTPS
4. **Backups**: Regular database and application backups
5. **Updates**: Keep system and dependencies updated

## 📈 Performance Optimization

1. **Database**: Add indexes for frequently queried columns
2. **Caching**: Use Redis for better cache performance  
3. **Static Files**: Serve via Nginx directly
4. **Gunicorn**: Adjust worker count based on CPU cores
5. **Connection Pooling**: Optimize PostgreSQL connections