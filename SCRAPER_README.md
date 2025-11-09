# LMN Radgona Scraper - Navodila za uporabo

## 📋 Opis

Scraper za LMN Radgona Liga A, ki avtomatsko shranjuje podatke o tekmah v PostgreSQL bazo.

## ⏰ Časovni razpored

Scraper se avtomatsko zažene:
- **Sobota ob 23:00**
- **Nedelja ob 23:00**

Scrapa:
- ✅ **Liga A** - trenutni krog
- ✅ **Liga B** - trenutni krog

**Ne scrapa vseh krogov** za optimalno hitrost in manjšo obremenitev strežnika.

## 🚀 Namestitev

### 1. Namesti potrebne pakete
```bash
pip install -r requirements.txt
```

Ali specifično:
```bash
pip install schedule requests beautifulsoup4 psycopg2-binary python-dotenv
```

### 2. Nastavi DATABASE_URL
Ustvari `.env` datoteko z:
```
DATABASE_URL=postgresql://user:password@host:port/database
```

## 💻 Uporaba

### Produkcijski način (Scheduler)
Zažene scheduler, ki čaka na soboto/nedeljo ob 23:00:
```bash
python scraper_radgona.py --schedule
```

**Izgled:**
```
============================================================
SCRAPER SCHEDULER STARTED
============================================================
Current time: 2025-11-09 11:09:07
Schedule: Every Saturday and Sunday at 23:00
Target: Liga A + Liga B - Current round only
Database: ✓ Enabled
============================================================

Waiting for scheduled times...
(Press Ctrl+C to stop)
```

### Testni način (Takojšnje izvajanje)
Zažene scraping takoj (za testiranje):
```bash
python scraper_radgona.py --test-now
```

**Izgled:**
```
Running test scrape now...
[DATABASE] Initializing database...
[DATABASE] ✓ Database ready

============================================================
[SCHEDULED SCRAPE] Starting at 2025-11-09 11:08:37
============================================================

────────────────────────────────────────────────────────────
[Liga A] Starting scrape...
────────────────────────────────────────────────────────────

[Liga A] ✓ Scraped 6 matches from: 13. krog
[Liga A] Available rounds: 26

[Liga A] Sample matches from 13. krog:
  1. Ivanjševska slatina 1 - 3 Očeslavci - Sobota, 08.11.2025 18:00
  2. Negova 5 - 1 Baren - Sobota, 08.11.2025 18:00
  3. Lokavec 3 - 3 Podgrad - Sobota, 08.11.2025 18:00
  ... and 3 more matches

[Liga A] Saving 6 matches to database...
[Liga A] ✓ Successfully saved to database

────────────────────────────────────────────────────────────
[Liga B] Starting scrape...
────────────────────────────────────────────────────────────

[Liga B] ✓ Scraped 8 matches from: 12. krog
[Liga B] Available rounds: 24
...

============================================================
[SCHEDULED SCRAPE] Completed at 2025-11-09 11:08:43
[SUMMARY] Total matches scraped: 14
[SUMMARY] Total matches saved: 14
============================================================
```

### Hiter pregled (Brez baze)
Prikaže navodila in naredi hiter test brez shranjevanja:
```bash
python scraper_radgona.py
```

## 🗄️ Shranjeni podatki

Scraper shranjuje v tabelo `matches` z naslednjimi podatki:
- `match_unique_id` - Unikatni ID tekme
- `league_id` - ID lige (npr. "liga_a")
- `round_name` - Ime kroga (npr. "13. krog")
- `round_url` - URL kroga
- `date_str` - Datum kot string
- `date_obj` - Datum kot DATE objekt
- `time` - Ura tekme
- `home_team` - Domača ekipa
- `away_team` - Gostujoča ekipa
- `score_str` - Rezultat (npr. "3 - 1" ali "N/P")
- `venue` - Lokacija
- `last_scraped` - Čas zadnjega scrapanja

### Deduplikacija
- Če tekma že obstaja v bazi (isti `match_unique_id`), se posodobi samo `score_str` in `last_scraped`
- To omogoča posodobitev rezultatov za tekme, ki so bile prvotno označene kot "N/P"

## 🔧 Produkcijska uporaba

### Linux (systemd service)

1. Ustvari service datoteko `/etc/systemd/system/lmn-scraper.service`:
```ini
[Unit]
Description=LMN Radgona Scraper
After=network.target

[Service]
Type=simple
User=yourusername
WorkingDirectory=/path/to/lmn-radgona
Environment="DATABASE_URL=postgresql://..."
ExecStart=/usr/bin/python3 /path/to/lmn-radgona/scraper_radgona.py --schedule
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

2. Omogoči in zaženi:
```bash
sudo systemctl enable lmn-scraper
sudo systemctl start lmn-scraper
sudo systemctl status lmn-scraper
```

### Windows (Task Scheduler)

1. Odpri Task Scheduler
2. Create Basic Task
3. Trigger: Weekly → Sobota in Nedelja → 23:00
4. Action: Start a program
   - Program: `python.exe`
   - Arguments: `C:\path\to\scraper_radgona.py --test-now`
   - Start in: `C:\path\to\lmn-radgona`

**Opomba:** Za Windows Task Scheduler uporabi `--test-now` način, ker scheduler v skriptu zahteva da proces teče 24/7.

### Docker

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scraper_radgona.py .
COPY database.py .

ENV DATABASE_URL=postgresql://...

CMD ["python", "scraper_radgona.py", "--schedule"]
```

Zaženi:
```bash
docker build -t lmn-scraper .
docker run -d --name lmn-scraper --restart unless-stopped lmn-scraper
```

## 🐛 Debugging

Vklopi debug način z environment variablo:
```bash
export SCRAPER_DEBUG=true
python scraper_radgona.py --test-now
```

To prikaže dodatne informacije:
- HTTP requeste
- Cloudflare detection
- Parsing details
- Tabele v HTML

## 📊 Rate Limiting

Scraper ima vgrajene varovalke:
- **5 retry poskusov** z eksponentnim backoff-om
- **Rotirajoči User-Agents** (Desktop + Mobile)
- **Human-like delays** (2-5 sekund med requesti)
- **Cloudflare detection** in retry logika

**Priporočilo:** Ne scrapaj pogosteje kot 2-3x dnevno.

## ⚠️ Opozorila

1. **Cloudflare zaščita:** Spletna stran uporablja Cloudflare. Preveč pogosto scrapanje lahko povzroči blokado IP naslova.

2. **Database connection:** Če baza ni dosegljiva, scraper bo še vedno deloval, vendar ne bo shranjeval podatkov.

3. **Scheduler 24/7:** `--schedule` način zahteva, da proces teče ves čas. Za produkcijo uporabi systemd/Docker.

## 📝 Spremembe

- **v1.0** - Začetna verzija z ročnim testom
- **v2.0** - Dodana scheduler funkcionalnost (sobota/nedelja 23:00)
- **v2.1** - Dodana integracija z PostgreSQL bazo
