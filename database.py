import sqlite3
import json
from datetime import datetime, timedelta

DATABASE_NAME = 'lmn_radgona_cache.db'
CACHE_DURATION_ROUNDS = timedelta(hours=24) # How long to cache the list of rounds
CACHE_DURATION_MATCHES = timedelta(hours=1)  # How long to cache individual round matches
CACHE_DURATION_LEADERBOARD = timedelta(hours=1) # How long to cache calculated leaderboard

def is_round_in_past(league_id, round_url):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT date_obj FROM matches WHERE league_id = ? AND round_url = ?', (league_id, round_url))
    rows = cursor.fetchall()
    conn.close()
    now = datetime.now().date()
    return all(datetime.fromisoformat(row['date_obj']).date() < now - timedelta(days=2) for row in rows if row['date_obj'])


def get_db_connection():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row # Access columns by name
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Table for storing when a league's general info (like rounds list) was last fetched
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leagues_meta (
            league_id TEXT PRIMARY KEY,
            rounds_json TEXT,              -- JSON string of available_rounds
            last_fetched_rounds TIMESTAMP
        )
    ''')

    # Table for storing matches - this will be the source for leaderboard calculation
    # And also for individual round display if we cache aggressively
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            match_unique_id TEXT PRIMARY KEY, -- e.g., league_id + home_team + away_team + round_name + date_str
            league_id TEXT NOT NULL,
            round_name TEXT,
            round_url TEXT, -- The URL this specific match's round was found on (for re-fetching specific round)
            date_str TEXT,
            date_obj TEXT,    -- Store as ISO format string YYYY-MM-DD
            time TEXT,
            home_team TEXT,
            away_team TEXT,
            score_str TEXT,
            venue TEXT,
            last_scraped TIMESTAMP
        )
    ''')
    # Index for faster lookups
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_league_round ON matches (league_id, round_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_league_date ON matches (league_id, date_obj)")


    # Table for storing pre-calculated leaderboards
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS calculated_leaderboards (
            league_id TEXT PRIMARY KEY,
            leaderboard_data_json TEXT, -- JSON string of the leaderboard list
            last_calculated TIMESTAMP,
            source_data_hash TEXT     -- Hash of relevant match data to check for changes
        )
    ''')
    conn.commit()
    conn.close()
    print("Database initialized.")

# --- Functions for Leagues Meta & Rounds ---
def get_cached_rounds(league_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT rounds_json, last_fetched_rounds FROM leagues_meta WHERE league_id = ?", (league_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row['rounds_json'] and row['last_fetched_rounds']:
        last_fetched = datetime.fromisoformat(row['last_fetched_rounds'])
        if datetime.now() - last_fetched < CACHE_DURATION_ROUNDS:
            print(f"Using cached rounds for {league_id}, fetched at {last_fetched}")
            return json.loads(row['rounds_json'])
    return None

def cache_rounds(league_id, rounds_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO leagues_meta (league_id, rounds_json, last_fetched_rounds)
        VALUES (?, ?, ?)
    ''', (league_id, json.dumps(rounds_data), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    print(f"Cached rounds for {league_id}")

# --- Functions for Matches ---
def get_cached_round_matches(league_id, round_url):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Get the minimum last_scraped time for this round_url
    cursor.execute('''
        SELECT MIN(last_scraped) as oldest_scrape_time 
        FROM matches 
        WHERE league_id = ? AND round_url = ?
    ''', (league_id, round_url))
    staleness_check_row = cursor.fetchone()

    if staleness_check_row and staleness_check_row['oldest_scrape_time']:
        oldest_scrape_dt = datetime.fromisoformat(staleness_check_row['oldest_scrape_time'])
        if is_round_in_past(league_id, round_url):
            # Cache is fresh, retrieve all matches for this round_url
            cursor.execute('''
                SELECT * FROM matches 
                WHERE league_id = ? AND round_url = ? 
                ORDER BY date_obj, time
            ''', (league_id, round_url))
            rows = cursor.fetchall()
            conn.close()
            
            matches = []
            for row_data in rows:
                match = dict(row_data)
                if match.get('date_obj'):
                    try: match['date_obj'] = datetime.fromisoformat(match['date_obj']).date()
                    except: match['date_obj'] = None
                matches.append(match)
            
            if matches:
                print(f"Using {len(matches)} cached (and fresh) matches for round URL: {round_url}")
                return matches
        else:
            print(f"Match cache for {round_url} is STALE (oldest scrape: {oldest_scrape_dt}).")
    else:
        print(f"No existing cache entries or scrape times for {round_url}.")

    conn.close()
    return None # Cache miss or stale


def cache_matches(league_id, round_url, matches_data):
    if not matches_data:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.now().isoformat()
    
    for match in matches_data:
        # Ensure date_obj is string or None for DB
        date_obj_str = match['date_obj'].isoformat() if match['date_obj'] else None
        
        # Create a more robust unique ID
        match_unique_id = f"{league_id}_{match['home_team']}_{match['away_team']}_{match.get('round_name', 'unknownround')}_{match.get('date_str', 'nodate')}"
        
        cursor.execute('''
            INSERT OR REPLACE INTO matches 
            (match_unique_id, league_id, round_name, round_url, date_str, date_obj, time, home_team, away_team, score_str, venue, last_scraped)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            match_unique_id, league_id, match.get('round_name'), round_url,
            match['date_str'], date_obj_str, match['time'],
            match['home_team'], match['away_team'], match['score_str'],
            match['venue'], now_iso
        ))
    conn.commit()
    conn.close()
    print(f"Cached {len(matches_data)} matches for round URL: {round_url}")

def get_all_matches_for_league(league_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM matches WHERE league_id = ? ORDER BY date_obj, time", (league_id,))
    rows = cursor.fetchall()
    conn.close()
    
    matches = []
    for row_data in rows:
        match = dict(row_data)
        if match.get('date_obj'):
            try:
                match['date_obj'] = datetime.fromisoformat(match['date_obj']).date()
            except:
                match['date_obj'] = None
        matches.append(match)
    return matches

# --- Functions for Leaderboard ---
def get_cached_leaderboard(league_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT leaderboard_data_json, last_calculated 
        FROM calculated_leaderboards WHERE league_id = ?
    ''', (league_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row['leaderboard_data_json'] and row['last_calculated']:
        last_calculated = datetime.fromisoformat(row['last_calculated'])
        # For leaderboard, staleness depends on whether underlying match data changed.
        # A simple time-based cache is also an option here.
        # For now, let's use a simple time cache.
        if datetime.now() - last_calculated < CACHE_DURATION_LEADERBOARD:
            print(f"Using cached leaderboard for {league_id}, calculated at {last_calculated}")
            return json.loads(row['leaderboard_data_json'])
    return None

def cache_leaderboard(league_id, leaderboard_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO calculated_leaderboards 
        (league_id, leaderboard_data_json, last_calculated)
        VALUES (?, ?, ?)
    ''', (league_id, json.dumps(leaderboard_data), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    print(f"Cached leaderboard for {league_id}")


if __name__ == '__main__':
    init_db()
    # Example usage (optional, for testing the DB functions directly)
    # cache_rounds("liga_a_test", [{"name": "1. krog", "url": "http://example.com/1", "id": "1"}])
    # rounds = get_cached_rounds("liga_a_test")
    # print("Test cached rounds:", rounds)