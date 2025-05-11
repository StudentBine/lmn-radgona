import os
import json
from datetime import datetime, timedelta
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from contextlib import contextmanager

load_dotenv()

# --- Constants ---
CACHE_DURATION_ROUNDS = timedelta(hours=24)
CACHE_DURATION_MATCHES = timedelta(hours=1)
CACHE_DURATION_LEADERBOARD = timedelta(hours=1)

# --- Database connection pool ---
_db_pool = None

def init_db_pool():
    global _db_pool
    if _db_pool is None:
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            raise RuntimeError("DATABASE_URL environment variable is not set.")
        _db_pool = pool.SimpleConnectionPool(1, 10, db_url, cursor_factory=RealDictCursor)

def get_db_connection():
    if _db_pool is None:
        init_db_pool()
    return _db_pool.getconn()

def release_db_connection(conn):
    if _db_pool:
        _db_pool.putconn(conn)

@contextmanager
def db_cursor():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    finally:
        release_db_connection(conn)

# --- Database schema initialization ---
def init_db():
    with db_cursor() as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS leagues_meta (
                league_id TEXT PRIMARY KEY,
                rounds_json TEXT,
                last_fetched_rounds TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS matches (
                match_unique_id TEXT PRIMARY KEY,
                league_id TEXT NOT NULL,
                round_name TEXT,
                round_url TEXT,
                date_str TEXT,
                date_obj DATE,
                time TEXT,
                home_team TEXT,
                away_team TEXT,
                score_str TEXT,
                venue TEXT,
                last_scraped TIMESTAMP
            )
        ''')

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_matches_league_round ON matches (league_id, round_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_matches_league_date ON matches (league_id, date_obj)')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS calculated_leaderboards (
                league_id TEXT PRIMARY KEY,
                leaderboard_data_json TEXT,
                last_calculated TIMESTAMP,
                source_data_hash TEXT
            )
        ''')

    print("PostgreSQL database initialized.")

# --- Leagues Meta ---
def get_cached_rounds(league_id):
    with db_cursor() as cursor:
        cursor.execute("SELECT rounds_json, last_fetched_rounds FROM leagues_meta WHERE league_id = %s", (league_id,))
        row = cursor.fetchone()

    if row and row['rounds_json'] and row['last_fetched_rounds']:
        last_fetched = row['last_fetched_rounds']
        if datetime.now() - last_fetched < CACHE_DURATION_ROUNDS:
            print(f"Using cached rounds for {league_id}, fetched at {last_fetched}")
            return json.loads(row['rounds_json'])
    return None

def cache_rounds(league_id, rounds_data):
    with db_cursor() as cursor:
        cursor.execute('''
            INSERT INTO leagues_meta (league_id, rounds_json, last_fetched_rounds)
            VALUES (%s, %s, %s)
            ON CONFLICT (league_id) DO UPDATE SET
            rounds_json = EXCLUDED.rounds_json,
            last_fetched_rounds = EXCLUDED.last_fetched_rounds
        ''', (league_id, json.dumps(rounds_data), datetime.now()))
    print(f"Cached rounds for {league_id}")

# --- Matches ---
def get_cached_round_matches(league_id, round_url):
    with db_cursor() as cursor:
        cursor.execute('''
            SELECT MIN(last_scraped) AS oldest_scrape_time 
            FROM matches 
            WHERE league_id = %s AND round_url = %s
        ''', (league_id, round_url))
        result = cursor.fetchone()

        if result and result['oldest_scrape_time']:
            oldest = result['oldest_scrape_time']
            if datetime.now() - oldest < CACHE_DURATION_MATCHES:
                cursor.execute('''
                    SELECT * FROM matches 
                    WHERE league_id = %s AND round_url = %s 
                    ORDER BY date_obj, time
                ''', (league_id, round_url))
                rows = cursor.fetchall()
                print(f"Using {len(rows)} cached (and fresh) matches for round URL: {round_url}")
                return rows
            else:
                print(f"Match cache for {round_url} is STALE (oldest scrape: {oldest}).")
        else:
            print(f"No existing cache entries or scrape times for {round_url}.")
    return None

def cache_matches(league_id, round_url, matches_data):
    if not matches_data:
        return
    now = datetime.now()
    with db_cursor() as cursor:
        for match in matches_data:
            date_obj_val = match['date_obj'] if match['date_obj'] else None
            match_unique_id = f"{league_id}_{match['home_team']}_{match['away_team']}_{match.get('round_name', 'unknownround')}_{match.get('date_str', 'nodate')}"
            cursor.execute('''
                INSERT INTO matches 
                (match_unique_id, league_id, round_name, round_url, date_str, date_obj, time, home_team, away_team, score_str, venue, last_scraped)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (match_unique_id) DO UPDATE SET
                    score_str = EXCLUDED.score_str,
                    last_scraped = EXCLUDED.last_scraped
            ''', (
                match_unique_id, league_id, match.get('round_name'), round_url,
                match['date_str'], date_obj_val, match['time'],
                match['home_team'], match['away_team'], match['score_str'],
                match['venue'], now
            ))
    print(f"Cached {len(matches_data)} matches for round URL: {round_url}")

def get_all_matches_for_league(league_id):
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM matches WHERE league_id = %s ORDER BY date_obj, time", (league_id,))
        return cursor.fetchall()

# --- Leaderboard ---
def get_cached_leaderboard(league_id):
    with db_cursor() as cursor:
        cursor.execute("SELECT leaderboard_data_json, last_calculated FROM calculated_leaderboards WHERE league_id = %s", (league_id,))
        row = cursor.fetchone()

    if row and row['leaderboard_data_json'] and row['last_calculated']:
        if datetime.now() - row['last_calculated'] < CACHE_DURATION_LEADERBOARD:
            print(f"Using cached leaderboard for {league_id}, calculated at {row['last_calculated']}")
            return json.loads(row['leaderboard_data_json'])
    return None

def cache_leaderboard(league_id, leaderboard_data):
    with db_cursor() as cursor:
        cursor.execute('''
            INSERT INTO calculated_leaderboards (league_id, leaderboard_data_json, last_calculated)
            VALUES (%s, %s, %s)
            ON CONFLICT (league_id) DO UPDATE SET
                leaderboard_data_json = EXCLUDED.leaderboard_data_json,
                last_calculated = EXCLUDED.last_calculated
        ''', (league_id, json.dumps(leaderboard_data), datetime.now()))
    print(f"Cached leaderboard for {league_id}")

if __name__ == '__main__':
    init_db_pool()
    init_db()
