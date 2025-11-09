# Render Deployment - LMN Radgona

## 📋 Pregled

Aplikacija se deployа na **Render** z dvema servisoma:
1. **Web Service** - Flask aplikacija (app_radgona.py)
2. **Background Worker** - Scraper scheduler (scraper_radgona.py)

## 🚀 Avtomatski Deployment preko GitHub

### 1. Pripravi GitHub Repozitorij

```bash
# Inicializiraj git (če še ni)
cd /path/to/lmn-radgona
git init

# Dodaj .gitignore (že obstaja)
# Dodaj vse datoteke
git add .
git commit -m "Initial commit - LMN Radgona app with scraper"

# Poveži z GitHub repozitorijem
git remote add origin https://github.com/YOUR_USERNAME/lmn-radgona.git
git branch -M main
git push -u origin main
```

### 2. Nastavi Render

#### A) Ustvari račun
1. Pojdi na [render.com](https://render.com)
2. Registriraj se ali se prijavi z GitHub računom

#### B) Poveži GitHub repozitorij
1. Dashboard → **New +** → **Blueprint**
2. Izberi **Connect a repository**
3. Avtoriziraj GitHub dostop
4. Izberi repozitorij `lmn-radgona`

#### C) Render bo samodejno prebral `render.yaml`
Render bo ustvaril **1 servis**:
- ✅ **lmn-radgona** (Web Service) - Flask app

**Opomba:** Scraper se bo zaganjal preko zunanjega cron servisa (zastonj), ne pa z Render Background Workerjem (plačljivo $7/mesec). Glej `CRON_SETUP.md` za navodila.

### 3. Nastavi Environment Variables

Za web servis nastavi:

#### Web Service (`lmn-radgona`)
```
DATABASE_URL=postgresql://user:password@host:port/database
FLASK_SECRET_KEY=your-secret-key-here
CRON_SECRET_KEY=your-cron-secret-key-here
FLASK_ENV=production
SCRAPER_DEBUG=false
SCRAPER_MAX_WORKERS=2
REDIS_URL=redis://... (optional)
```

**Pomembno:** `CRON_SECRET_KEY` je potreben za avtomatski scraping preko zunanjega cron servisa!

#### Kako dodati spremenljivke:
1. Render Dashboard → Izberi servis
2. **Environment** → **Add Environment Variable**
3. Dodaj key/value pare
4. **Save Changes** (servis se bo avtomatsko re-deployал)

### 4. PostgreSQL Baza na Render

#### Opcija A: Render PostgreSQL (Priporočeno)
1. Dashboard → **New +** → **PostgreSQL**
2. Ime: `lmn-radgona-db`
3. Plan: **Free** (300MB)
4. Ustvari bazo
5. Kopiraj **Internal Database URL**
6. Prilepi v `DATABASE_URL` za oba servisa

#### Opcija B: Zunanja baza
- Uporabi Supabase, ElephantSQL, ali drugo PostgreSQL bazo
- Kopiraj connection string v `DATABASE_URL`

### 5. Nastavi Avtomatski Scraping (POMEMBNO!)

**Ne pozabi nastaviti zunanjega cron servisa!**

Scraper se **ne bo avtomatsko zaganjal** brez tega koraka!

👉 **Glej `CRON_SETUP.md` za podrobna navodila**

Hitri koraki:
1. Registriraj se na EasyCron.com (zastonj)
2. Ustvari cron job za soboto 23:00
3. Ustvari cron job za nedeljo 23:00
4. URL: `https://lmn-radgona.onrender.com/cron/scrape-leagues?secret=<CRON_SECRET_KEY>`

To bo avtomatsko scrapalo obe ligi vsako soboto in nedeljo!

### 6. Testiranje Deployment-a

Ko je deployment končan:

#### Preveri Web Service:
```
https://lmn-radgona.onrender.com
```

#### Testni Scrape (ročno):
```bash
curl "https://lmn-radgona.onrender.com/cron/scrape-leagues?secret=<CRON_SECRET_KEY>"
```

#### Preveri Logs:
1. Render Dashboard → **lmn-radgona**
2. **Logs** tab
3. Išči "scrape" za scraping aktivnost

## 🔄 Avtomatski Re-deployment

**Ko pushaš na GitHub, se Render avtomatsko re-deploya!**

```bash
# Naredi spremembe v kodi
git add .
git commit -m "Update scraper logic"
git push origin main

# Render bo avtomatsko zaznal push in re-deployал oba servisa
```

### Kaj sproži re-deployment:
- ✅ Push na `main` branch
- ✅ Pull request merge
- ✅ Spremembe v katerikoli datoteki

### Opazuj deployment:
1. Render Dashboard → Servisi
2. **Events** tab prikaže deployment progress
3. **Logs** prikaže build in runtime logs

## 📊 Monitoring

### Web Service Health Check
```bash
curl https://lmn-radgona.onrender.com/
```

### Preveri Scraper Worker Status
1. Render Dashboard → **lmn-radgona-scraper**
2. **Metrics** tab
3. Preveri:
   - ✅ Status: **Running**
   - ✅ Memory usage
   - ✅ CPU usage

### Preveri Database
```bash
# Prek Render dashboard
Dashboard → lmn-radgona-db → Metrics

# Ročno (če imaš psql)
psql $DATABASE_URL
\dt  -- Prikaži tabele
SELECT COUNT(*) FROM matches;  -- Preveri število zapisov
```

## 🐛 Troubleshooting

### Web Service ne deluje
```bash
# Preveri logs
Dashboard → lmn-radgona → Logs

# Pogosti problemi:
# 1. DATABASE_URL ni nastavljen
# 2. Port binding - Render nastavi $PORT avtomatsko
# 3. Dependencies - preveri requirements.txt
```

### Scraper Worker ne deluje
```bash
# Preveri logs
Dashboard → lmn-radgona-scraper → Logs

# Pogosti problemi:
# 1. DATABASE_URL ni nastavljen
# 2. schedule package ni installiran (preveri requirements.txt)
# 3. Memory limit exceeded (Free tier: 512MB)
```

### Baza ni dosegljiva
```bash
# Preveri connection string
echo $DATABASE_URL

# Testraj povezavo
python -c "import psycopg2; conn = psycopg2.connect('$DATABASE_URL'); print('Connected!')"
```

### Scraper ne scrapa ob pravem času
```bash
# Preveri časovni pas
# Render uporablja UTC timezone!

# Če želiš 23:00 CET (Central European Time):
# To je 22:00 UTC pozimi ali 21:00 UTC poleti

# Spremeni v scraper_radgona.py:
schedule.every().saturday.at("22:00").do(scheduled_scrape_job)  # Za CET
```

## 🆓 Free Tier Limitacije

### Web Service (Free)
- ✅ 750 ur/mesec (dovolj za 24/7)
- ⚠️ Po 15 minutah neaktivnosti se "spanje" (cold start)
- ⚠️ 512MB RAM
- ⚠️ Ni custom domain (brez plačila)

### Externí Cron Service (EasyCron Free)
- ✅ 1000 cron jobov/dan
- ✅ Unlimited cron jobs
- ✅ Email notifications

### PostgreSQL (Free)
- ✅ 300MB storage
- ⚠️ Po 90 dnevih brez aktivnosti se izbriše
- ⚠️ 1 milijon vrstic limit

**SKUPAJ: $0/mesec** 🎉

*(Vs. Background Worker rešitev: $7/mesec)*

## 🔐 Varnost

### Environment Variables
**NIKOLI** ne commitaj:
- ❌ `DATABASE_URL`
- ❌ `FLASK_SECRET_KEY`
- ❌ API keys
- ❌ Passwords

✅ Vse to je že v `.gitignore` (`.env`, `.env.*`)

### GitHub Secrets (Opcijsko)
Če želiš CI/CD pipeline z GitHub Actions:
```yaml
# .github/workflows/deploy.yml
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      # Render hook bo avtomatsko triggeran
```

## 📈 Scaling (V prihodnosti)

Ko prelevi free tier:

### Upgrade Web Service
```
Free → Starter ($7/mesec)
- 512MB → 1GB RAM
- Brez cold starts
- Custom domain
```

### Upgrade Background Worker
```
Free → Starter ($7/mesec)
- 512MB → 1GB RAM
- Več CPU
```

### Upgrade Database
```
Free → Starter ($7/mesec)
- 300MB → 1GB storage
- Več povezav
- Backup/restore
```

## 📚 Dodatni Viri

- [Render Documentation](https://render.com/docs)
- [Blueprint Spec](https://render.com/docs/blueprint-spec)
- [Background Workers](https://render.com/docs/background-workers)
- [Environment Variables](https://render.com/docs/environment-variables)

## ✅ Checklist za Prvi Deployment

- [ ] GitHub repozitorij ustvarjen in pushal
- [ ] Render račun ustvarjen
- [ ] GitHub connected z Render
- [ ] Blueprint deployan (`render.yaml`)
- [ ] PostgreSQL baza ustvarjena
- [ ] `DATABASE_URL` nastavljen za web service
- [ ] `FLASK_SECRET_KEY` nastavljen
- [ ] `CRON_SECRET_KEY` nastavljen (**POMEMBNO!**)
- [ ] Web service deluje (odpri URL)
- [ ] **EasyCron račun ustvarjen** (**KRITIČNO!**)
- [ ] **Cron job za soboto nastavljен** (**KRITIČNO!**)
- [ ] **Cron job za nedeljo nastavljen** (**KRITIČNO!**)
- [ ] Testni scrape izveden (ročno preko URL-ja)
- [ ] Podatki v bazi (preveri tabelo `matches`)

**⚠️ Brez nastavitve cron servisa scraper NE BO DELOVAL!**

## 🎉 Po Prvi Uspešni Deployment

**Avtomatizacija deluje!**

Vsak push na GitHub → Render avtomatsko deploya → Scraper teče vsako soboto/nedeljo ob 23:00 → Podatki v bazi → Flask app prikazuje rezultate

**To je vse! 🚀**
