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
CACHE_DURATION_ROUNDS = timedelta(days=7)   # Rounds rarely change - cache for a week
CACHE_DURATION_MATCHES = timedelta(hours=24)  # Extended to 24 hours for better round navigation  
CACHE_DURATION_LEADERBOARD = timedelta(hours=6)  # Cache leaderboard for 6 hours for speed

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

        # Admin tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password TEXT NOT NULL,
                permissions TEXT[], -- Array of permissions
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS teams (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                league_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, league_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS players (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                team_id INTEGER REFERENCES teams(id) ON DELETE CASCADE,
                jersey_number INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cards (
                id SERIAL PRIMARY KEY,
                match_id INTEGER,
                player_id INTEGER REFERENCES players(id) ON DELETE CASCADE,
                card_type VARCHAR(20) NOT NULL, -- 'yellow' or 'red'
                minute INTEGER,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create match_results table for detailed match results
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS match_results (
                id SERIAL PRIMARY KEY,
                match_id TEXT REFERENCES matches(match_unique_id) UNIQUE,
                home_team_id INTEGER REFERENCES teams(id),
                away_team_id INTEGER REFERENCES teams(id),
                home_score INTEGER DEFAULT 0,
                away_score INTEGER DEFAULT 0,
                status VARCHAR(20) DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'in_progress', 'finished', 'postponed', 'cancelled')),
                match_date DATE,
                venue TEXT,
                referee TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create goals table for tracking individual goals
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS goals (
                id SERIAL PRIMARY KEY,
                match_result_id INTEGER REFERENCES match_results(id) ON DELETE CASCADE,
                player_id INTEGER REFERENCES players(id),
                team_id INTEGER REFERENCES teams(id),
                minute INTEGER,
                goal_type VARCHAR(20) DEFAULT 'regular' CHECK (goal_type IN ('regular', 'penalty', 'own_goal', 'free_kick', 'header')),
                assist_player_id INTEGER REFERENCES players(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create match_cards table for tracking cards in matches  
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS match_cards (
                id SERIAL PRIMARY KEY,
                match_result_id INTEGER REFERENCES match_results(id) ON DELETE CASCADE,
                player_id INTEGER REFERENCES players(id),
                team_id INTEGER REFERENCES teams(id),
                card_type VARCHAR(10) NOT NULL CHECK (card_type IN ('yellow', 'red')),
                minute INTEGER,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create default admin user if none exists
        try:
            cursor.execute("SELECT COUNT(*) FROM admin_users")
            result = cursor.fetchone()
            admin_count = 0
            if result:
                if hasattr(result, 'count'):
                    admin_count = result.count
                elif isinstance(result, (list, tuple)) and len(result) > 0:
                    admin_count = result[0]
                else:
                    admin_count = result
        except Exception as e:
            print(f"Error checking admin users: {e}")
            admin_count = 0
        
        if admin_count == 0:
            try:
                from werkzeug.security import generate_password_hash
                default_password = generate_password_hash('admin123')
                permissions = ['manage_users', 'manage_teams', 'manage_players', 'manage_results', 'manage_cards', 'view_statistics']
                cursor.execute('''
                    INSERT INTO admin_users (username, password, permissions)
                    VALUES (%s, %s, %s)
                ''', ('admin', default_password, permissions))
                print("Created default admin user: admin / admin123")
            except Exception as e:
                print(f"Error creating default admin user: {e}")

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
        params = []
        for match in matches_data:
            date_obj_val = match['date_obj'] if match['date_obj'] else None
            match_unique_id = f"{league_id}_{match['home_team']}_{match['away_team']}_{match.get('round_name', 'unknownround')}_{match.get('date_str', 'nodate')}"
            params.append((
                match_unique_id, league_id, match.get('round_name'), round_url,
                match['date_str'], date_obj_val, match['time'],
                match['home_team'], match['away_team'], match['score_str'],
                match['venue'], now
            ))
        cursor.executemany('''
            INSERT INTO matches 
            (match_unique_id, league_id, round_name, round_url, date_str, date_obj, time, home_team, away_team, score_str, venue, last_scraped)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (match_unique_id) DO UPDATE SET
                score_str = EXCLUDED.score_str,
                last_scraped = EXCLUDED.last_scraped
        ''', params)
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

def clear_league_cache(league_id):
    """Clear all cached data for a specific league"""
    with db_cursor() as cursor:
        # Clear rounds cache
        cursor.execute("DELETE FROM leagues_meta WHERE league_id = %s", (league_id,))
        # Clear matches cache  
        cursor.execute("DELETE FROM matches WHERE league_id = %s", (league_id,))
        # Clear leaderboard cache
        cursor.execute("DELETE FROM calculated_leaderboards WHERE league_id = %s", (league_id,))
    print(f"Cleared all cache for league: {league_id}")

def get_all_teams_for_league(league_id):
    """Get all unique team names that appear in matches for a league"""
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT DISTINCT home_team as team FROM matches WHERE league_id = %s
            UNION
            SELECT DISTINCT away_team as team FROM matches WHERE league_id = %s
            ORDER BY team
        """, (league_id, league_id))
        teams = [row['team'] for row in cursor.fetchall()]
    return teams

# === Admin User Functions ===
def get_admin_user(username):
    """Get admin user by username"""
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM admin_users WHERE username = %s", (username,))
        return cursor.fetchone()

def get_admin_user_by_id(user_id):
    """Get admin user by ID"""
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM admin_users WHERE id = %s", (user_id,))
        return cursor.fetchone()

def get_all_admin_users():
    """Get all admin users"""
    with db_cursor() as cursor:
        cursor.execute("SELECT id, username, permissions, created_at FROM admin_users ORDER BY username")
        return cursor.fetchall()

def create_admin_user(username, password, permissions):
    """Create new admin user"""
    try:
        with db_cursor() as cursor:
            cursor.execute('''
                INSERT INTO admin_users (username, password, permissions)
                VALUES (%s, %s, %s)
            ''', (username, password, permissions))
            return True
    except psycopg2.IntegrityError:
        return False

def update_admin_user(user_id, data):
    """Update admin user"""
    try:
        with db_cursor() as cursor:
            set_clause = []
            values = []
            
            if 'password' in data:
                set_clause.append("password = %s")
                values.append(data['password'])
            
            if 'permissions' in data:
                set_clause.append("permissions = %s")
                values.append(data['permissions'])
            
            set_clause.append("updated_at = CURRENT_TIMESTAMP")
            values.append(user_id)
            
            query = f"UPDATE admin_users SET {', '.join(set_clause)} WHERE id = %s"
            cursor.execute(query, values)
            return True
    except Exception:
        return False

def delete_admin_user(user_id):
    """Delete admin user"""
    try:
        with db_cursor() as cursor:
            cursor.execute("DELETE FROM admin_users WHERE id = %s", (user_id,))
            return True
    except Exception:
        return False

# === Statistics Functions ===
def get_total_matches():
    """Get total number of matches"""
    with db_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM matches")
        result = cursor.fetchone()
        return result['count'] if result else 0

def get_total_teams():
    """Get total number of unique teams"""
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(DISTINCT team) FROM (
                SELECT home_team as team FROM matches
                UNION
                SELECT away_team as team FROM matches
            ) teams
        """)
        result = cursor.fetchone()
        return result['count'] if result else 0

def get_total_admin_users():
    """Get total number of admin users"""
    with db_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM admin_users")
        result = cursor.fetchone()
        return result['count'] if result else 0

# === Team Management Functions ===
def get_all_teams(league_filter=None):
    """Get all teams, optionally filtered by league"""
    with db_cursor() as cursor:
        if league_filter:
            cursor.execute("""
                SELECT t.*, 
                       COUNT(p.id) as player_count
                FROM teams t
                LEFT JOIN players p ON t.id = p.team_id
                WHERE t.league_id = %s
                GROUP BY t.id, t.name, t.league_id, t.created_at, t.updated_at
                ORDER BY t.name
            """, (league_filter,))
        else:
            cursor.execute("""
                SELECT t.*, 
                       COUNT(p.id) as player_count
                FROM teams t
                LEFT JOIN players p ON t.id = p.team_id
                GROUP BY t.id, t.name, t.league_id, t.created_at, t.updated_at
                ORDER BY t.name
            """)
        return cursor.fetchall()

def get_team_by_id(team_id):
    """Get team by ID with player count"""
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT t.*, 
                   COUNT(p.id) as player_count
            FROM teams t
            LEFT JOIN players p ON t.id = p.team_id
            WHERE t.id = %s
            GROUP BY t.id, t.name, t.league_id, t.created_at, t.updated_at
        """, (team_id,))
        return cursor.fetchone()

def create_team(name, league_id):
    """Create new team"""
    try:
        with db_cursor() as cursor:
            cursor.execute("""
                INSERT INTO teams (name, league_id)
                VALUES (%s, %s)
                RETURNING id
            """, (name, league_id))
            return cursor.fetchone()['id']
    except Exception as e:
        print(f"Error creating team: {e}")
        return None

def update_team(team_id, name, league_id):
    """Update existing team"""
    try:
        with db_cursor() as cursor:
            cursor.execute("""
                UPDATE teams 
                SET name = %s, league_id = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (name, league_id, team_id))
            return cursor.rowcount > 0
    except Exception as e:
        print(f"Error updating team: {e}")
        return False

def delete_team(team_id):
    """Delete team (will cascade delete players)"""
    try:
        with db_cursor() as cursor:
            cursor.execute("DELETE FROM teams WHERE id = %s", (team_id,))
            return cursor.rowcount > 0
    except Exception as e:
        print(f"Error deleting team: {e}")
        return False

def get_team_by_name(name, exclude_id=None):
    """Check if team name exists (for uniqueness validation)"""
    with db_cursor() as cursor:
        if exclude_id:
            cursor.execute("SELECT * FROM teams WHERE name = %s AND id != %s", (name, exclude_id))
        else:
            cursor.execute("SELECT * FROM teams WHERE name = %s", (name,))
        return cursor.fetchone()

def get_teams_count_by_league():
    """Get count of teams per league"""
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT league_id, COUNT(*) as count
            FROM teams
            GROUP BY league_id
        """)
        result = {row['league_id']: row['count'] for row in cursor.fetchall()}
        return {
            'liga_a': result.get('liga_a', 0),
            'liga_b': result.get('liga_b', 0),
            'total': sum(result.values())
        }

# === Player Management Functions ===
def get_players_by_team(team_id):
    """Get all players for specific team"""
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT p.*, t.name as team_name, t.league_id as team_league_id
            FROM players p
            JOIN teams t ON p.team_id = t.id
            WHERE p.team_id = %s
            ORDER BY p.jersey_number, p.name
        """, (team_id,))
        return cursor.fetchall()

def get_all_players():
    """Get all players with team information"""
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT p.*, t.name as team_name, t.league_id as team_league_id
            FROM players p
            JOIN teams t ON p.team_id = t.id
            ORDER BY t.name, p.jersey_number, p.name
        """)
        return cursor.fetchall()

def get_player_by_id(player_id):
    """Get player by ID with team information"""
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT p.*, t.name as team_name, t.league_id as team_league_id
            FROM players p
            JOIN teams t ON p.team_id = t.id
            WHERE p.id = %s
        """, (player_id,))
        return cursor.fetchone()

def create_player(name, team_id, jersey_number=None):
    """Create new player"""
    try:
        with db_cursor() as cursor:
            cursor.execute("""
                INSERT INTO players (name, team_id, jersey_number)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (name, team_id, jersey_number))
            return cursor.fetchone()['id']
    except Exception as e:
        print(f"Error creating player: {e}")
        return None

def update_player(player_id, name, team_id, jersey_number=None):
    """Update existing player"""
    try:
        with db_cursor() as cursor:
            cursor.execute("""
                UPDATE players 
                SET name = %s, team_id = %s, jersey_number = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (name, team_id, jersey_number, player_id))
            return cursor.rowcount > 0
    except Exception as e:
        print(f"Error updating player: {e}")
        return False

def delete_player(player_id):
    """Delete player"""
    try:
        with db_cursor() as cursor:
            cursor.execute("DELETE FROM players WHERE id = %s", (player_id,))
            return cursor.rowcount > 0
    except Exception as e:
        print(f"Error deleting player: {e}")
        return False

def check_jersey_number_available(team_id, jersey_number, exclude_player_id=None):
    """Check if jersey number is available in team"""
    if not jersey_number:
        return True
    
    with db_cursor() as cursor:
        if exclude_player_id:
            cursor.execute("""
                SELECT COUNT(*) FROM players 
                WHERE team_id = %s AND jersey_number = %s AND id != %s
            """, (team_id, jersey_number, exclude_player_id))
        else:
            cursor.execute("""
                SELECT COUNT(*) FROM players 
                WHERE team_id = %s AND jersey_number = %s
            """, (team_id, jersey_number))
        
        result = cursor.fetchone()
        return result['count'] == 0 if result else True

# === Match Results Functions ===
def get_all_matches_for_results():
    """Get all matches that can have detailed results"""
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT m.match_unique_id, m.home_team, m.away_team, m.league_id, 
                   m.date_str, m.score_str, m.venue,
                   mr.id as result_id, mr.home_score, mr.away_score, mr.status
            FROM matches m
            LEFT JOIN match_results mr ON m.match_unique_id = mr.match_id
            ORDER BY m.date_obj DESC, m.league_id
        """)
        return cursor.fetchall()

def get_match_result_by_id(result_id):
    """Get detailed match result by result_id"""
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT mr.*, m.home_team, m.away_team, m.league_id, m.date_str, m.venue,
                   ht.name as home_team_name, at.name as away_team_name
            FROM match_results mr
            JOIN matches m ON mr.match_id = m.match_unique_id
            LEFT JOIN teams ht ON mr.home_team_id = ht.id
            LEFT JOIN teams at ON mr.away_team_id = at.id
            WHERE mr.id = %s
        """, (result_id,))
        return cursor.fetchone()

def get_match_result_by_match_id(match_id):
    """Get match result by match_id"""
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT mr.*, m.home_team, m.away_team, m.league_id, m.date_str, m.venue,
                   ht.name as home_team_name, at.name as away_team_name
            FROM match_results mr
            JOIN matches m ON mr.match_id = m.match_unique_id
            LEFT JOIN teams ht ON mr.home_team_id = ht.id
            LEFT JOIN teams at ON mr.away_team_id = at.id
            WHERE mr.match_id = %s
        """, (match_id,))
        return cursor.fetchone()

def create_match_result(match_id, home_team_id, away_team_id, home_score=0, away_score=0, status='finished'):
    """Create detailed match result"""
    with db_cursor() as cursor:
        cursor.execute("""
            INSERT INTO match_results (match_id, home_team_id, away_team_id, home_score, away_score, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (match_id, home_team_id, away_team_id, home_score, away_score, status))
        return cursor.fetchone()['id']

def update_match_result(result_id, home_score, away_score, status='finished', referee=None, notes=None):
    """Update match result"""
    with db_cursor() as cursor:
        cursor.execute("""
            UPDATE match_results 
            SET home_score = %s, away_score = %s, status = %s, referee = %s, notes = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (home_score, away_score, status, referee, notes, result_id))
        return cursor.rowcount > 0

# === Goals Functions ===
def add_goal(match_result_id, player_id, team_id, minute, goal_type='regular', assist_player_id=None):
    """Add goal to match"""
    with db_cursor() as cursor:
        cursor.execute("""
            INSERT INTO goals (match_result_id, player_id, team_id, minute, goal_type, assist_player_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (match_result_id, player_id, team_id, minute, goal_type, assist_player_id))
        return cursor.fetchone()['id']

def get_match_goals(match_result_id):
    """Get all goals for a match"""
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT g.*, p.name as player_name, p.jersey_number, t.name as team_name,
                   ap.name as assist_player_name
            FROM goals g
            JOIN players p ON g.player_id = p.id
            JOIN teams t ON g.team_id = t.id
            LEFT JOIN players ap ON g.assist_player_id = ap.id
            WHERE g.match_result_id = %s
            ORDER BY g.minute
        """, (match_result_id,))
        return cursor.fetchall()

def delete_goal(goal_id):
    """Delete goal"""
    with db_cursor() as cursor:
        cursor.execute("DELETE FROM goals WHERE id = %s", (goal_id,))
        return cursor.rowcount > 0

# === Cards Functions ===
def add_card(match_result_id, player_id, team_id, card_type, minute, reason=None):
    """Add card to match"""
    with db_cursor() as cursor:
        cursor.execute("""
            INSERT INTO match_cards (match_result_id, player_id, team_id, card_type, minute, reason)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (match_result_id, player_id, team_id, card_type, minute, reason))
        return cursor.fetchone()['id']

def get_match_cards(match_result_id):
    """Get all cards for a match"""
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT mc.*, p.name as player_name, p.jersey_number, t.name as team_name
            FROM match_cards mc
            JOIN players p ON mc.player_id = p.id
            JOIN teams t ON mc.team_id = t.id
            WHERE mc.match_result_id = %s
            ORDER BY mc.minute
        """, (match_result_id,))
        return cursor.fetchall()

def delete_card(card_id):
    """Delete card"""
    with db_cursor() as cursor:
        cursor.execute("DELETE FROM match_cards WHERE id = %s", (card_id,))
        return cursor.rowcount > 0

# === Helper Functions ===
def get_team_players(team_id):
    """Get all players for a team"""
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT id, name, jersey_number
            FROM players 
            WHERE team_id = %s
            ORDER BY jersey_number
        """, (team_id,))
        return cursor.fetchall()

def find_team_by_name(team_name, league_id=None):
    """Find team by name"""
    with db_cursor() as cursor:
        if league_id:
            cursor.execute("SELECT id, name FROM teams WHERE name = %s AND league_id = %s", (team_name, league_id))
        else:
            cursor.execute("SELECT id, name FROM teams WHERE name = %s", (team_name,))
        return cursor.fetchone()

def get_match_by_unique_id(match_unique_id):
    """Get match by unique ID"""
    with db_cursor() as cursor:
        cursor.execute("""
            SELECT * FROM matches WHERE match_unique_id = %s
        """, (match_unique_id,))
        return cursor.fetchone()

def get_match_details(match_unique_id, league_id):
    """Get complete match details including goals and cards"""
    with db_cursor() as cursor:
        # First get the match
        cursor.execute("""
            SELECT * FROM matches WHERE match_unique_id = %s
        """, (match_unique_id,))
        match = cursor.fetchone()
        
        if not match:
            return None
        
        # Get match_result if it exists
        cursor.execute("""
            SELECT * FROM match_results WHERE match_id = %s
        """, (match_unique_id,))
        match_result = cursor.fetchone()
        
        if not match_result:
            # No detailed data yet
            return {
                'match': dict(match),
                'goals': {'home': [], 'away': []},
                'cards': {'home': [], 'away': []}
            }
        
        # Get goals
        cursor.execute("""
            SELECT g.*, p.name as player_name, p.jersey_number, t.name as team_name,
                   ap.name as assist_player_name
            FROM goals g
            JOIN players p ON g.player_id = p.id
            JOIN teams t ON g.team_id = t.id
            LEFT JOIN players ap ON g.assist_player_id = ap.id
            WHERE g.match_result_id = %s
            ORDER BY g.minute
        """, (match_result['id'],))
        all_goals = cursor.fetchall()
        
        # Get cards
        cursor.execute("""
            SELECT mc.*, p.name as player_name, p.jersey_number, t.name as team_name
            FROM match_cards mc
            JOIN players p ON mc.player_id = p.id
            JOIN teams t ON mc.team_id = t.id
            WHERE mc.match_result_id = %s
            ORDER BY mc.minute
        """, (match_result['id'],))
        all_cards = cursor.fetchall()
        
        # Separate goals and cards by team
        home_team = match['home_team']
        away_team = match['away_team']
        
        home_goals = [dict(g) for g in all_goals if g['team_name'] == home_team]
        away_goals = [dict(g) for g in all_goals if g['team_name'] == away_team]
        
        home_cards = [dict(c) for c in all_cards if c['team_name'] == home_team]
        away_cards = [dict(c) for c in all_cards if c['team_name'] == away_team]
        
        return {
            'match': dict(match),
            'match_result': dict(match_result) if match_result else None,
            'goals': {
                'home': home_goals,
                'away': away_goals
            },
            'cards': {
                'home': home_cards,
                'away': away_cards
            }
        }

if __name__ == '__main__':
    init_db_pool()
    init_db()
