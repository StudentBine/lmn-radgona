from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_caching import Cache
from flask_compress import Compress
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from scraper_radgona import fetch_lmn_radgona_data, BASE_URL, parse_score
from datetime import datetime
from urllib.parse import urljoin
from collections import defaultdict
import database
import os
import hashlib
import json
import logging
import time

# Configure logging - use simpler approach that works everywhere
try:
    # Try to log to file if possible, otherwise just console
    log_handlers = []
    if os.path.exists('/var/log') and os.access('/var/log', os.W_OK):
        log_handlers.append(logging.FileHandler('/var/log/lmn-radgona.log'))
    log_handlers.append(logging.StreamHandler())
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=log_handlers
    )
except:
    # Fallback to basic console logging
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

app = Flask(__name__)
Compress(app)


def leaderboard_matches_hash(matches):
    if not matches:
        return ''
    return hashlib.sha256(json.dumps(matches, sort_keys=True, default=str).encode()).hexdigest()

# Use Redis for cache if available, else fallback to SimpleCache
cache_config = {
    'CACHE_TYPE': 'RedisCache' if os.environ.get('REDIS_URL') else 'SimpleCache',
    'CACHE_REDIS_URL': os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
}
cache = Cache(app, config=cache_config)

# Flask config for sessions and admin
app.secret_key = os.environ.get('SECRET_KEY', 'lmn-radgona-secret-key-2025')

# Initialize database with error handling
try:
    database.init_db_pool()
    database.init_db()
    logger.info("Database initialized successfully")
except Exception as db_error:
    logger.error(f"Database initialization failed: {db_error}")
    # Continue without database for debugging routes

# Admin permissions
ADMIN_PERMISSIONS = {
    'add_teams': 'Dodajanje ekip',
    'edit_teams': 'Urejanje ekip', 
    'delete_teams': 'Brisanje ekip',
    'add_players': 'Dodajanje igralcev',
    'edit_players': 'Urejanje igralcev',
    'delete_players': 'Brisanje igralcev',
    'add_cards': 'Dodajanje kartonov',
    'add_results': 'Dodajanje rezultatov',
    'edit_results': 'Urejanje rezultatov',
    'manage_users': 'Upravljanje uporabnikov'
}

# Decorator for admin authentication
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        print(f"DEBUG admin_required: Session contents: {dict(session)}")
        print(f"DEBUG admin_required: admin_logged_in in session: {'admin_logged_in' in session}")
        if 'admin_logged_in' not in session:
            flash('Potrebna je prijava za dostop do admin panela.', 'error')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# Decorator for specific permissions
def permission_required(permission):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'admin_logged_in' not in session:
                flash('Potrebna je prijava.', 'error')
                return redirect(url_for('admin_login'))
            
            user_permissions = session.get('admin_permissions', [])
            if permission not in user_permissions and 'manage_users' not in user_permissions:
                flash('Nimate dovoljenja za to dejanje.', 'error')
                return redirect(url_for('admin_dashboard'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

LEAGUES_CONFIG = {
    "liga_a": {
        "name": "Liga A",
        "display_name": "Liga -A-",
        "main_results_page_url": urljoin(BASE_URL, "/index.php/ct-menu-item-7/razpored-liga-a"),
    },
    "liga_b": {
        "name": "Liga B",
        "display_name": "Liga -B-",
        "main_results_page_url": urljoin(BASE_URL, "/index.php/2017-08-11-13-54-06/razpored-liga-b"),
    }
}
DEFAULT_LEAGUE_ID = "liga_a"

@app.context_processor
def inject_global_vars():
    return dict(
        DEFAULT_LEAGUE_ID=DEFAULT_LEAGUE_ID,
        leagues=LEAGUES_CONFIG
    )

def calculate_leaderboard(all_matches_for_league, league_id):
    # Definirajmo vse ekipe za vsako ligo (na podlagi originalne strani)
    ALL_TEAMS = {
        'liga_a': [
            'Spodnja Ščavnica', 'Tiha voda', 'Lokavec', 'Podgrad', 'Plitvica', 
            'Negova', 'Očeslavci', 'Stari hrast', 'Baren', 'Radenska', 
            'Kapela', 'Ivanjševska slatina', 'Dinamo Radgona', 'Lešane'
        ],
        'liga_b': [
            'Ihova', 'Grabonoš', 'Police', 'Bumefekt', 'Mahovci', 'Šenekar',
            'Stavešinci', 'Segovci', 'Vrabel', 'Zoro', 'Hrastko', 'Porkys', 'Črešnjevci'
        ]
    }
    
    team_stats = defaultdict(lambda: {'played': 0, 'won': 0, 'drawn': 0, 'lost': 0,
                                      'goals_for': 0, 'goals_against': 0, 'goal_difference': 0,
                                      'points': 0, 'name': '', 'css_class': ''})
    
    # Mapiranje imen (scraped imena -> standardna imena)
    NAME_MAPPING = {
        'liga_a': {
            'Sp. Ščavnica': 'Spodnja Ščavnica',
            'Dinamo': 'Dinamo Radgona',
            # Dodajte druge preslikave po potrebi
        },
        'liga_b': {
            # Dodajte preslikave za Liga B po potrebi
        }
    }
    
    # Inicializiraj vse ekipe za to ligo z 0 vrednostmi
    if league_id in ALL_TEAMS:
        for team_name in ALL_TEAMS[league_id]:
            team_stats[team_name]['name'] = team_name
    
    if not all_matches_for_league:
        # Vrni vse ekipe z 0 vrednostmi, če ni tekem
        return [stats for stats in team_stats.values()]
    for match in all_matches_for_league:
        home_raw = match['home_team']
        away_raw = match['away_team']
        score_str = match['score_str']
        
        # Mapiraj imena ekip na standardna imena
        home = NAME_MAPPING.get(league_id, {}).get(home_raw, home_raw)
        away = NAME_MAPPING.get(league_id, {}).get(away_raw, away_raw)
        
        # Preveri, ali sta ekipi v seznamu veljavnih ekip za to ligo
        if league_id in ALL_TEAMS:
            if home not in ALL_TEAMS[league_id]:
                logger.warning(f"Neznana ekipa v {league_id}: {home} (original: {home_raw})")
                continue
            if away not in ALL_TEAMS[league_id]:
                logger.warning(f"Neznana ekipa v {league_id}: {away} (original: {away_raw})")
                continue
        
        # Nastavi ime ekipe če še ni nastavljeno
        if not team_stats[home]['name']:
            team_stats[home]['name'] = home
        if not team_stats[away]['name']:
            team_stats[away]['name'] = away
        hg, ag = parse_score(score_str)
        if hg is not None and ag is not None:
            team_stats[home]['played'] += 1
            team_stats[away]['played'] += 1
            team_stats[home]['goals_for'] += hg
            team_stats[home]['goals_against'] += ag
            team_stats[away]['goals_for'] += ag
            team_stats[away]['goals_against'] += hg
            if hg > ag:
                team_stats[home]['won'] += 1
                team_stats[home]['points'] += 3
                team_stats[away]['lost'] += 1
            elif ag > hg:
                team_stats[away]['won'] += 1
                team_stats[away]['points'] += 3
                team_stats[home]['lost'] += 1
            else:
                team_stats[home]['drawn'] += 1
                team_stats[away]['drawn'] += 1
                team_stats[home]['points'] += 1
                team_stats[away]['points'] += 1
    leaderboard = []
    for team, stats in team_stats.items():
        stats['goal_difference'] = stats['goals_for'] - stats['goals_against']
        leaderboard.append(stats)
    # Sort once by all criteria
    leaderboard.sort(key=lambda x: (x['points'], x['goal_difference'], x['goals_for'], x['name']), reverse=True)

    # CSS class assignment (cleaned)
    for team in leaderboard:
        team['css_class'] = ''
    if leaderboard:
        leaderboard[0]['css_class'] = 'top-place'
        if league_id == 'liga_a' and len(leaderboard) > 1:
            # Liga A: zadnja dva mesta označena kot izpadla
            leaderboard[-1]['css_class'] = 'last-place'
            if len(leaderboard) > 2:
                leaderboard[-2]['css_class'] = 'last-place'
        elif league_id == 'liga_b' and len(leaderboard) > 1:
            # Liga B: prvo in drugo mesto označeno za napredovanje  
            if len(leaderboard) > 1:
                leaderboard[1]['css_class'] = 'top-place'
    return leaderboard

@app.route('/health')
def health_check():
    """Simple health check"""
    return {'status': 'ok', 'timestamp': datetime.now().isoformat()}, 200

@app.route('/')
def index():
    return redirect(url_for('home'))


@cache.cached(timeout=300, query_string=True)
@app.route('/league/<league_id>/results', methods=['GET', 'POST'])
def show_league_results(league_id):
    try:
        if league_id not in LEAGUES_CONFIG:
            return redirect(url_for('show_league_results', league_id=DEFAULT_LEAGUE_ID))

        league_config = LEAGUES_CONFIG[league_id]
        target_round_url = league_config["main_results_page_url"]

        # POST > prefer user form; else GET arg
        if request.method == 'POST' and request.form.get('league_id_form_field') == league_id:
            form_selected_url = request.form.get('round_select_url')
            if form_selected_url:
                target_round_url = form_selected_url
        elif request.args.get('round_url'):
            target_round_url = request.args.get('round_url')

        available_rounds = database.get_cached_rounds(league_id)
        initial_page_round_info = None

        if not available_rounds:
            try:
                _, _, scraped_rounds, scraped_initial = fetch_lmn_radgona_data(
                    league_config["main_results_page_url"], fetch_all_rounds_data=False, league_id_for_caching=league_id)
                if scraped_rounds:
                    available_rounds = scraped_rounds
                    initial_page_round_info = scraped_initial
                    database.cache_rounds(league_id, scraped_rounds)
                    logger.info(f"Successfully scraped {len(scraped_rounds)} rounds for {league_id}")
                else:
                    logger.warning(f"No rounds scraped for {league_id}")
            except Exception as scrape_error:
                logger.error(f"Failed to scrape rounds for {league_id}: {scrape_error}")
                available_rounds = []
        else:
            if target_round_url == league_config["main_results_page_url"]:
                _, _, _, temp_initial = fetch_lmn_radgona_data(league_config["main_results_page_url"], False, league_id_for_caching=league_id)
                initial_page_round_info = temp_initial

        if target_round_url == league_config["main_results_page_url"] and initial_page_round_info and initial_page_round_info.get('url'):
            target_round_url = initial_page_round_info['url']

        page_matches = database.get_cached_round_matches(league_id, target_round_url)
        round_details = next((r for r in available_rounds or [] if r['url'] == target_round_url), None)

        if page_matches is None:
            try:
                scraped_matches, _, _, scraped_round_info = fetch_lmn_radgona_data(
                    target_round_url, fetch_all_rounds_data=False, league_id_for_caching=league_id)
                if scraped_matches:
                    database.cache_matches(league_id, target_round_url, scraped_matches)
                    page_matches = scraped_matches
                    round_details = scraped_round_info
                    logger.info(f"Successfully scraped {len(scraped_matches)} matches for round")
                else:
                    logger.warning(f"No matches scraped for round {target_round_url}")
                    page_matches = []
                    if not round_details:
                        round_details = {'name': 'Ni podatkov', 'url': target_round_url}
            except Exception as scrape_error:
                logger.error(f"Failed to scrape matches for {target_round_url}: {scrape_error}")
                page_matches = []
                if not round_details:
                    round_details = {'name': 'Napaka pri nalaganju', 'url': target_round_url}
        elif not round_details:
            round_details = {'name': 'Krog (iz predpomn.)', 'url': target_round_url}

        grouped_data = defaultdict(list)
        for match in page_matches:
            grouped_data[match['date_str']].append(match)

        return render_template('results_radgona.html',
                               grouped_results=dict(grouped_data),
                               all_rounds=available_rounds or [],
                               current_selected_url=target_round_url,
                               page_title_main=f"LMN Radgona: {league_config['display_name']}",
                               page_title_section=round_details.get('name', 'Rezultati'),
                               source_url_for_data=target_round_url,
                               today_date=datetime.now().date(),
                               current_league_id=league_id)
    except Exception as e:
        logger.error(f"Error in show_league_results for {league_id}: {str(e)}")
        try:
            return render_template('error.html', 
                                   error_message="Napaka pri pridobivanju rezultatov", 
                                   error_code=500), 500
        except:
            # Fallback if error.html template doesn't exist
            return f"<h1>Napaka pri pridobivanju rezultatov</h1><p>Koda napake: 500</p><p><a href='/'>Nazaj na domačo stran</a></p>", 500

@app.route('/league/<league_id>/leaderboard')
def show_leaderboard(league_id):
    try:
        if league_id not in LEAGUES_CONFIG:
            return redirect(url_for('show_leaderboard', league_id=DEFAULT_LEAGUE_ID))

        force_refresh = request.args.get('force', 'false').lower() == 'true'
        clear_cache_param = request.args.get('clear_cache', 'false').lower() == 'true'
        
        if clear_cache_param:
            database.clear_league_cache(league_id)
            cache.clear()
            logger.info(f"Cache cleared for {league_id}")
        leaderboard_data = None if force_refresh else database.get_cached_leaderboard(league_id)

        if leaderboard_data is None or force_refresh:
            rounds = database.get_cached_rounds(league_id)
            current_round_info = None
            if not rounds:
                _, _, rounds, current_round_info = fetch_lmn_radgona_data(
                    LEAGUES_CONFIG[league_id]['main_results_page_url'], fetch_all_rounds_data=False, league_id_for_caching=league_id)
                if rounds:
                    database.cache_rounds(league_id, rounds)
            if rounds:
                current_round_info = rounds[-1] if not current_round_info else current_round_info
                if database.get_cached_round_matches(league_id, current_round_info['url']) is None:
                    scraped, _, _, _ = fetch_lmn_radgona_data(current_round_info['url'], fetch_all_rounds_data=False, league_id_for_caching=league_id)
                    if scraped:
                        database.cache_matches(league_id, current_round_info['url'], scraped)
            # Parallel scrape all rounds for leaderboard
            try:
                # Try simpler approach first - just get current round
                page_matches_test, _, rounds_test, current_round_test = fetch_lmn_radgona_data(
                    LEAGUES_CONFIG[league_id]['main_results_page_url'], fetch_all_rounds_data=False, league_id_for_caching=league_id)
                
                if page_matches_test and rounds_test:
                    logger.info(f"Successfully scraped {len(page_matches_test)} matches and {len(rounds_test)} rounds for {league_id}")
                    # Now try to get all matches
                    _, all_matches, _, _ = fetch_lmn_radgona_data(
                        LEAGUES_CONFIG[league_id]['main_results_page_url'], fetch_all_rounds_data=True, league_id_for_caching=league_id)
                    if all_matches:
                        logger.info(f"Successfully scraped {len(all_matches)} total matches for {league_id}")
                    else:
                        logger.warning(f"Failed to scrape all matches for {league_id}, using cached data")
                        all_matches = database.get_all_matches_for_league(league_id)
                else:
                    logger.warning(f"Failed to scrape basic data for {league_id}, using cached data")
                    all_matches = database.get_all_matches_for_league(league_id)
            except Exception as scrape_error:
                logger.error(f"Scraping failed for {league_id}: {scrape_error}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                # Uporabi cached podatke kot fallback
                all_matches = database.get_all_matches_for_league(league_id)
                if not all_matches:
                    logger.warning(f"No cached data available for {league_id}")
            
            leaderboard_data = calculate_leaderboard(all_matches, league_id)
            if leaderboard_data:
                database.cache_leaderboard(league_id, leaderboard_data)

        return render_template('leaderboard.html',
                               leaderboard_data=leaderboard_data,
                               page_title_main=f"LMN Radgona: {LEAGUES_CONFIG[league_id]['display_name']}",
                               page_title_section="Lestvica",
                               current_league_id=league_id,
                               source_url_for_data=LEAGUES_CONFIG[league_id]['main_results_page_url'])
    except Exception as e:
        logger.error(f"Error in show_leaderboard for {league_id}: {str(e)}")
        try:
            return render_template('error.html', 
                                   error_message="Napaka pri pridobivanju lestvice", 
                                   error_code=500), 500
        except:
            # Fallback if error.html template doesn't exist
            return f"<h1>Napaka pri pridobivanju lestvice</h1><p>Koda napake: 500</p><p><a href='/'>Nazaj na domačo stran</a></p>", 500


@app.route('/home')
def home():
    return render_template('home.html')

@app.route('/admin/clear-cache/<league_id>')
def clear_cache(league_id):
    """Admin route to clear cache for a specific league"""
    if league_id in LEAGUES_CONFIG:
        try:
            database.clear_league_cache(league_id)
            cache.clear()  # Clear Flask cache as well
            return f"Cache cleared for {LEAGUES_CONFIG[league_id]['name']}", 200
        except Exception as e:
            logger.error(f"Error clearing cache for {league_id}: {str(e)}")
            return f"Error clearing cache: {str(e)}", 500
    else:
        return "Invalid league ID", 404

@app.route('/admin/fix-teams/<league_id>')
def fix_missing_teams(league_id):
    """Admin route to ensure all teams are in leaderboard"""
    if league_id not in LEAGUES_CONFIG:
        return "Invalid league ID", 404
    
    try:
        # Clear cache first
        database.clear_league_cache(league_id)
        cache.clear()
        
        # Force refresh leaderboard with all teams
        all_matches = database.get_all_matches_for_league(league_id)
        leaderboard_data = calculate_leaderboard(all_matches, league_id)
        
        if leaderboard_data:
            database.cache_leaderboard(league_id, leaderboard_data)
        
        return f"Fixed teams for {LEAGUES_CONFIG[league_id]['name']}. Found {len(leaderboard_data)} teams.", 200
        
    except Exception as e:
        logger.error(f"Error fixing teams for {league_id}: {str(e)}")
        return f"Error: {str(e)}", 500

@app.route('/admin/debug')
def debug_panel():
    """Main debug panel"""
    return render_template('debug.html')

@app.route('/admin/debug/<league_id>')
def debug_league(league_id):
    """Debug route to show league data"""
    if league_id not in LEAGUES_CONFIG:
        return "Invalid league ID", 404
    
    try:
        # Get data from database
        all_matches = database.get_all_matches_for_league(league_id)
        rounds = database.get_cached_rounds(league_id)
        leaderboard = database.get_cached_leaderboard(league_id)
        
        # Get unique teams from database
        teams_from_db = database.get_all_teams_for_league(league_id)
        teams_from_matches = list(set([m['home_team'] for m in all_matches] + [m['away_team'] for m in all_matches])) if all_matches else []
        
        debug_info = {
            'league_id': league_id,
            'league_name': LEAGUES_CONFIG[league_id]['name'],
            'total_matches': len(all_matches) if all_matches else 0,
            'rounds_count': len(rounds) if rounds else 0,
            'leaderboard_teams': len(leaderboard) if leaderboard else 0,
            'sample_matches': all_matches[:3] if all_matches else [],
            'teams_from_database': teams_from_db,
            'teams_from_matches': teams_from_matches,
            'expected_teams_liga_a': ['Spodnja Ščavnica', 'Tiha voda', 'Lokavec', 'Podgrad', 'Plitvica', 'Negova', 'Očeslavci', 'Stari hrast', 'Baren', 'Radenska', 'Kapela', 'Ivanjševska slatina', 'Dinamo Radgona', 'Lešane'] if league_id == 'liga_a' else [],
            'expected_teams_liga_b': ['Ihova', 'Grabonoš', 'Police', 'Bumefekt', 'Mahovci', 'Šenekar', 'Stavešinci', 'Segovci', 'Vrabel', 'Zoro', 'Hrastko', 'Porkys', 'Črešnjevci'] if league_id == 'liga_b' else []
        }
        
        return f"<pre>{json.dumps(debug_info, indent=2, default=str)}</pre>"
        
    except Exception as e:
        return f"Debug error: {str(e)}", 500

@app.route('/admin/test-scraper/<league_id>')
def test_scraper(league_id):
    """Test scraper manually for debugging"""
    if league_id not in LEAGUES_CONFIG:
        return "Invalid league ID", 404
    
    try:
        url = LEAGUES_CONFIG[league_id]['main_results_page_url']
        start_time = datetime.now()
        
        # Test single page scrape first (no fetch all rounds)
        page_matches, _, rounds, current_round = fetch_lmn_radgona_data(url, fetch_all_rounds_data=False)
        
        # If single page works, try fetch all rounds
        all_matches = None
        if page_matches:
            try:
                _, all_matches, _, _ = fetch_lmn_radgona_data(url, fetch_all_rounds_data=True)
            except Exception as e:
                logger.error(f"Failed to fetch all rounds: {e}")
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        result = {
            'status': 'success',
            'league_id': league_id,
            'url': url,
            'duration_seconds': duration,
            'page_matches_count': len(page_matches) if page_matches else 0,
            'all_matches_count': len(all_matches) if all_matches else 0,
            'rounds_count': len(rounds) if rounds else 0,
            'current_round': current_round,
            'sample_matches': (page_matches or [])[:3]
        }
        
        return f"<pre>{json.dumps(result, indent=2, default=str)}</pre>"
        
    except Exception as e:
        logger.error(f"Test scraper error for {league_id}: {str(e)}")
        import traceback
        tb = traceback.format_exc()
        return f"<pre>Error testing scraper: {str(e)}\n\nTraceback:\n{tb}</pre>", 500

@app.route('/admin/env-check')
def env_check():
    """Check environment variables and system info"""
    try:
        import sys
        import platform
        env_info = {
            'python_version': sys.version,
            'platform': platform.platform(),
            'has_database_url': bool(os.environ.get('DATABASE_URL')),
            'has_secret_key': bool(os.environ.get('SECRET_KEY')),
            'scraper_debug': os.environ.get('SCRAPER_DEBUG', 'false'),
            'scraper_max_workers': os.environ.get('SCRAPER_MAX_WORKERS', '6'),
            'flask_env': os.environ.get('FLASK_ENV', 'development'),
            'port': os.environ.get('PORT', '5000')
        }
        return f"<pre>{json.dumps(env_info, indent=2)}</pre>"
    except Exception as e:
        return f"<pre>Error: {str(e)}</pre>", 500

@app.route('/admin/force-debug-test')
def force_debug_test():
    """Force debug mode and test the scraper"""
    try:
        # Temporarily enable debug mode
        original_debug = os.environ.get('SCRAPER_DEBUG', 'false')
        os.environ['SCRAPER_DEBUG'] = 'true'
        
        # Test Liga A URL
        url = "https://www.lmn-radgona.si/index.php/ct-menu-item-7/razpored-liga-a"
        
        logger.info(f"Starting forced debug test for: {url}")
        start_time = time.time()
        
        from scraper_radgona import fetch_lmn_radgona_data
        
        page_matches, all_matches, rounds, current_round = fetch_lmn_radgona_data(url)
        
        duration = time.time() - start_time
        
        # Restore original debug setting
        os.environ['SCRAPER_DEBUG'] = original_debug
        
        result = {
            'test_type': 'forced_debug_test',
            'timestamp': datetime.now().isoformat(),
            'url': url,
            'debug_enabled': True,
            'duration_seconds': duration,
            'page_matches_count': len(page_matches) if page_matches else 0,
            'rounds_count': len(rounds) if rounds else 0,
            'current_round': current_round,
            'sample_matches': (page_matches or [])[:2]
        }
        
        return f"<pre>{json.dumps(result, indent=2, default=str)}</pre>"
        
    except Exception as e:
        # Restore debug setting in case of error
        if 'original_debug' in locals():
            os.environ['SCRAPER_DEBUG'] = original_debug
            
        logger.error(f"Force debug test error: {str(e)}")
        import traceback
        tb = traceback.format_exc()
        return f"<pre>Error in force debug test: {str(e)}\n\nTraceback:\n{tb}</pre>", 500

@app.route('/admin/test-url/<league_id>')
def test_url_direct(league_id):
    """Test direct URL access"""
    if league_id not in LEAGUES_CONFIG:
        return "Invalid league ID", 404
    
    try:
        import requests
        from bs4 import BeautifulSoup
        
        url = LEAGUES_CONFIG[league_id]['main_results_page_url']
        
        # Test basic request
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'sl-SI,sl;q=0.9,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        result = {
            'url': url,
            'status_code': response.status_code,
            'content_type': response.headers.get('content-type', 'Unknown'),
            'content_length': len(response.content),
            'headers_sample': dict(list(response.headers.items())[:10])
        }
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            result['title'] = soup.title.string if soup.title else 'No title'
            
            # Check for tables
            tables = soup.find_all('table')
            result['total_tables'] = len(tables)
            
            fixtures_table = soup.find('table', class_='fixtures-results')
            result['has_fixtures_table'] = fixtures_table is not None
            
            if fixtures_table:
                rows = fixtures_table.find_all('tr')
                result['table_rows'] = len(rows)
        
        return f"<pre>{json.dumps(result, indent=2, default=str)}</pre>"
        
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return f"<pre>Error: {str(e)}\n\nTraceback:\n{tb}</pre>", 500


# Admin Routes
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        print(f"DEBUG: Login attempt - Username: {username}, Password: {'*' * len(password) if password else 'None'}")
        
        try:
            user = database.get_admin_user(username)
            print(f"DEBUG: User found: {user is not None}")
            
            if user:
                password_check = check_password_hash(user['password'], password)
                print(f"DEBUG: Password check result: {password_check}")
                
                if password_check:
                    session['admin_logged_in'] = True
                    session['admin_username'] = user['username']
                    session['admin_permissions'] = user['permissions']
                    flash('Uspešno ste se prijavili!', 'success')
                    print("DEBUG: Login successful, redirecting to dashboard")
                    return redirect(url_for('admin_dashboard'))
                else:
                    flash('Napačno uporabniško ime ali geslo.', 'error')
                    print("DEBUG: Password check failed")
            else:
                flash('Napačno uporabniško ime ali geslo.', 'error')
                print("DEBUG: User not found")
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            flash('Napaka pri prijavi.', 'error')
            print(f"DEBUG: Exception during login: {e}")
    
    return render_template('admin/login.html')

@app.route('/admin/logout')
@admin_required
def admin_logout():
    """Admin logout"""
    session.clear()
    flash('Uspešno ste se odjavili.', 'success')
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
@app.route('/admin')
@admin_required
def admin_dashboard():
    """Main admin dashboard"""
    try:
        # Get basic statistics
        stats = {
            'total_matches': database.get_total_matches(),
            'total_teams': database.get_total_teams(),
            'total_users': database.get_total_admin_users()
        }
        return render_template('admin/dashboard.html', stats=stats, permissions=ADMIN_PERMISSIONS)
    except Exception as e:
        logger.error(f"Dashboard error: {str(e)}")
        flash('Napaka pri nalaganju dashboard-a.', 'error')
        return render_template('admin/dashboard.html', stats={}, permissions=ADMIN_PERMISSIONS)

@app.route('/admin/users')
@permission_required('manage_users')
def admin_users():
    """User management page"""
    try:
        users = database.get_all_admin_users()
        return render_template('admin/users.html', users=users, permissions=ADMIN_PERMISSIONS)
    except Exception as e:
        logger.error(f"Users error: {str(e)}")
        flash('Napaka pri nalaganju uporabnikov.', 'error')
        return render_template('admin/users.html', users=[], permissions=ADMIN_PERMISSIONS)

@app.route('/admin/users/add', methods=['GET', 'POST'])
@permission_required('manage_users')
def admin_add_user():
    """Add new admin user"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        permissions = request.form.getlist('permissions')
        
        if not username or not password:
            flash('Uporabniško ime in geslo sta obvezna.', 'error')
        else:
            try:
                hashed_password = generate_password_hash(password)
                success = database.create_admin_user(username, hashed_password, permissions)
                if success:
                    flash('Uporabnik je bil uspešno dodan.', 'success')
                    return redirect(url_for('admin_users'))
                else:
                    flash('Uporabnik s tem imenom že obstaja.', 'error')
            except Exception as e:
                logger.error(f"Add user error: {str(e)}")
                flash('Napaka pri dodajanju uporabnika.', 'error')
    
    return render_template('admin/add_user.html', permissions=ADMIN_PERMISSIONS)

@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@permission_required('manage_users')
def admin_edit_user(user_id):
    """Edit admin user"""
    try:
        user = database.get_admin_user_by_id(user_id)
        if not user:
            flash('Uporabnik ne obstaja.', 'error')
            return redirect(url_for('admin_users'))
        
        if request.method == 'POST':
            permissions = request.form.getlist('permissions')
            password = request.form.get('password')
            
            update_data = {'permissions': permissions}
            if password:
                update_data['password'] = generate_password_hash(password)
            
            success = database.update_admin_user(user_id, update_data)
            if success:
                flash('Uporabnik je bil uspešno posodobljen.', 'success')
                return redirect(url_for('admin_users'))
            else:
                flash('Napaka pri posodabljanju uporabnika.', 'error')
        
        return render_template('admin/edit_user.html', user=user, permissions=ADMIN_PERMISSIONS)
    except Exception as e:
        logger.error(f"Edit user error: {str(e)}")
        flash('Napaka pri urejanju uporabnika.', 'error')
        return redirect(url_for('admin_users'))

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@permission_required('manage_users')
def admin_delete_user(user_id):
    """Delete admin user"""
    try:
        success = database.delete_admin_user(user_id)
        if success:
            flash('Uporabnik je bil uspešno odstranjen.', 'success')
        else:
            flash('Napaka pri brisanju uporabnika.', 'error')
    except Exception as e:
        logger.error(f"Delete user error: {str(e)}")
        flash('Napaka pri brisanju uporabnika.', 'error')
    
    return redirect(url_for('admin_users'))

# === Team Management Routes ===
@app.route('/admin/teams')
@admin_required
@permission_required('manage_teams')
def admin_teams():
    """Team management page"""
    try:
        league_filter = request.args.get('league')
        teams = database.get_all_teams(league_filter)
        counts = database.get_teams_count_by_league()
        
        return render_template('admin/teams.html', 
                             teams=teams,
                             filter_league=league_filter,
                             total_teams=counts['total'],
                             liga_a_count=counts['liga_a'],
                             liga_b_count=counts['liga_b'])
    except Exception as e:
        logger.error(f"Teams page error: {str(e)}")
        flash('Napaka pri nalaganju ekip.', 'error')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/teams/add', methods=['GET', 'POST'])
@admin_required
@permission_required('manage_teams')
def admin_add_team():
    """Add new team"""
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            league_id = request.form.get('league_id', '').strip()
            
            if not name or not league_id:
                flash('Ime ekipe in liga sta obvezna', 'error')
                return render_template('admin/add_team.html')
            
            if len(name) < 2:
                flash('Ime ekipe mora imeti vsaj 2 znaka', 'error')
                return render_template('admin/add_team.html')
            
            if league_id not in ['liga_a', 'liga_b']:
                flash('Neveljavna liga', 'error')
                return render_template('admin/add_team.html')
            
            # Check if team name already exists
            existing_team = database.get_team_by_name(name)
            if existing_team:
                flash('Ekipa s tem imenom že obstaja', 'error')
                return render_template('admin/add_team.html')
            
            # Create team
            team_id = database.create_team(name, league_id)
            if team_id:
                flash(f'Ekipa {name} je bila uspešno ustvarjena', 'success')
                return redirect(url_for('admin_teams'))
            else:
                flash('Napaka pri ustvarjanju ekipe', 'error')
                
        except Exception as e:
            logger.error(f"Add team error: {str(e)}")
            flash('Napaka pri dodajanju ekipe', 'error')
    
    try:
        counts = database.get_teams_count_by_league()
        return render_template('admin/add_team.html', 
                             liga_a_count=counts['liga_a'],
                             liga_b_count=counts['liga_b'])
    except:
        return render_template('admin/add_team.html')

@app.route('/admin/teams/<int:team_id>/edit', methods=['GET', 'POST'])
@admin_required
@permission_required('manage_teams')
def admin_edit_team(team_id):
    """Edit existing team"""
    try:
        team = database.get_team_by_id(team_id)
        if not team:
            flash('Ekipa ni bila najdena', 'error')
            return redirect(url_for('admin_teams'))
        
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            league_id = request.form.get('league_id', '').strip()
            
            if not name or not league_id:
                flash('Ime ekipe in liga sta obvezna', 'error')
                return render_template('admin/edit_team.html', team=team)
            
            if len(name) < 2:
                flash('Ime ekipe mora imeti vsaj 2 znaka', 'error')
                return render_template('admin/edit_team.html', team=team)
            
            if league_id not in ['liga_a', 'liga_b']:
                flash('Neveljavna liga', 'error')
                return render_template('admin/edit_team.html', team=team)
            
            # Check if team name is taken by another team
            existing_team = database.get_team_by_name(name, exclude_id=team_id)
            if existing_team:
                flash('Ekipa s tem imenom že obstaja', 'error')
                return render_template('admin/edit_team.html', team=team)
            
            # Update team
            if database.update_team(team_id, name, league_id):
                flash(f'Ekipa {name} je bila uspešno posodobljena', 'success')
                return redirect(url_for('admin_teams'))
            else:
                flash('Napaka pri posodabljanju ekipe', 'error')
        
        counts = database.get_teams_count_by_league()
        return render_template('admin/edit_team.html', 
                             team=team,
                             liga_a_count=counts['liga_a'],
                             liga_b_count=counts['liga_b'])
        
    except Exception as e:
        logger.error(f"Edit team error: {str(e)}")
        flash('Napaka pri urejanju ekipe', 'error')
        return redirect(url_for('admin_teams'))

@app.route('/admin/teams/<int:team_id>/delete', methods=['POST'])
@admin_required
@permission_required('manage_teams')
def admin_delete_team(team_id):
    """Delete team"""
    try:
        team = database.get_team_by_id(team_id)
        if not team:
            flash('Ekipa ni bila najdena', 'error')
            return redirect(url_for('admin_teams'))
        
        if database.delete_team(team_id):
            flash(f'Ekipa {team["name"]} je bila uspešno odstranjena', 'success')
        else:
            flash('Napaka pri odstranjevanju ekipe', 'error')
            
    except Exception as e:
        logger.error(f"Delete team error: {str(e)}")
        flash('Napaka pri odstranjevanju ekipe', 'error')
    
    return redirect(url_for('admin_teams'))

@app.route('/admin/teams/<int:team_id>/players')
@admin_required
@permission_required('manage_players')
def admin_team_players(team_id):
    """Team players management"""
    try:
        team = database.get_team_by_id(team_id)
        if not team:
            flash('Ekipa ni bila najdena', 'error')
            return redirect(url_for('admin_teams'))
        
        players = database.get_players_by_team(team_id)
        return render_template('admin/players.html', team=team, players=players)
        
    except Exception as e:
        logger.error(f"Team players error: {str(e)}")
        flash('Napaka pri nalaganju igralcev', 'error')
        return redirect(url_for('admin_teams'))

# === Player Management Routes ===
@app.route('/admin/players')
@admin_required
@permission_required('manage_players')
def admin_players():
    """All players management"""
    try:
        players = database.get_all_players()
        return render_template('admin/players.html', players=players, team=None)
    except Exception as e:
        logger.error(f"Players page error: {str(e)}")
        flash('Napaka pri nalaganju igralcev', 'error')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/players/add')
@app.route('/admin/teams/<int:team_id>/players/add')
@admin_required
@permission_required('manage_players')
def admin_add_player(team_id=None):
    """Add new player"""
    try:
        team = None
        teams = database.get_all_teams()
        
        if team_id:
            team = database.get_team_by_id(team_id)
            if not team:
                flash('Ekipa ni bila najdena', 'error')
                return redirect(url_for('admin_teams'))
        
        return render_template('admin/add_player.html', team=team, teams=teams)
        
    except Exception as e:
        logger.error(f"Add player page error: {str(e)}")
        flash('Napaka pri nalaganju strani', 'error')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/players/add', methods=['POST'])
@app.route('/admin/teams/<int:team_id>/players/add', methods=['POST'])
@admin_required
@permission_required('manage_players')
def admin_add_player_post(team_id=None):
    """Process add player form"""
    try:
        name = request.form.get('name', '').strip()
        form_team_id = request.form.get('team_id')
        jersey_number = request.form.get('jersey_number')
        
        # Use team_id from URL if available, otherwise from form
        final_team_id = team_id or (int(form_team_id) if form_team_id else None)
        
        if not name or not final_team_id:
            flash('Ime igralca in ekipa sta obvezna', 'error')
            return redirect(request.url)
        
        if len(name) < 2:
            flash('Ime igralca mora imeti vsaj 2 znaka', 'error')
            return redirect(request.url)
        
        # Validate jersey number if provided
        if jersey_number:
            try:
                jersey_number = int(jersey_number)
                if jersey_number < 1 or jersey_number > 99:
                    flash('Številka dresa mora biti med 1 in 99', 'error')
                    return redirect(request.url)
                
                # Check if jersey number is available
                if not database.check_jersey_number_available(final_team_id, jersey_number):
                    flash('Številka dresa je že zasedena v tej ekipi', 'error')
                    return redirect(request.url)
                    
            except ValueError:
                flash('Neveljavna številka dresa', 'error')
                return redirect(request.url)
        else:
            jersey_number = None
        
        # Verify team exists
        team = database.get_team_by_id(final_team_id)
        if not team:
            flash('Ekipa ni bila najdena', 'error')
            return redirect(request.url)
        
        # Create player
        player_id = database.create_player(name, final_team_id, jersey_number)
        if player_id:
            flash(f'Igralec {name} je bil uspešno dodan v ekipo {team["name"]}', 'success')
            return redirect(url_for('admin_team_players', team_id=final_team_id))
        else:
            flash('Napaka pri ustvarjanju igralca', 'error')
            
    except Exception as e:
        logger.error(f"Add player error: {str(e)}")
        flash('Napaka pri dodajanju igralca', 'error')
    
    return redirect(request.url)

@app.route('/admin/players/<int:player_id>/edit', methods=['GET', 'POST'])
@admin_required
@permission_required('manage_players')
def admin_edit_player(player_id):
    """Edit existing player"""
    try:
        player = database.get_player_by_id(player_id)
        if not player:
            flash('Igralec ni bil najden', 'error')
            return redirect(url_for('admin_players'))
        
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            team_id = request.form.get('team_id')
            jersey_number = request.form.get('jersey_number')
            
            if not name or not team_id:
                flash('Ime igralca in ekipa sta obvezna', 'error')
                return render_template('admin/edit_player.html', player=player, teams=database.get_all_teams())
            
            if len(name) < 2:
                flash('Ime igralca mora imeti vsaj 2 znaka', 'error')
                return render_template('admin/edit_player.html', player=player, teams=database.get_all_teams())
            
            # Validate jersey number if provided
            if jersey_number:
                try:
                    jersey_number = int(jersey_number)
                    if jersey_number < 1 or jersey_number > 99:
                        flash('Številka dresa mora biti med 1 in 99', 'error')
                        return render_template('admin/edit_player.html', player=player, teams=database.get_all_teams())
                    
                    # Check if jersey number is available (exclude current player)
                    if not database.check_jersey_number_available(int(team_id), jersey_number, player_id):
                        flash('Številka dresa je že zasedena v tej ekipi', 'error')
                        return render_template('admin/edit_player.html', player=player, teams=database.get_all_teams())
                        
                except ValueError:
                    flash('Neveljavna številka dresa', 'error')
                    return render_template('admin/edit_player.html', player=player, teams=database.get_all_teams())
            else:
                jersey_number = None
            
            # Verify team exists
            team = database.get_team_by_id(int(team_id))
            if not team:
                flash('Ekipa ni bila najdena', 'error')
                return render_template('admin/edit_player.html', player=player, teams=database.get_all_teams())
            
            # Update player
            if database.update_player(player_id, name, int(team_id), jersey_number):
                flash(f'Igralec {name} je bil uspešno posodobljen', 'success')
                return redirect(url_for('admin_team_players', team_id=int(team_id)))
            else:
                flash('Napaka pri posodabljanju igralca', 'error')
        
        teams = database.get_all_teams()
        return render_template('admin/edit_player.html', player=player, teams=teams)
        
    except Exception as e:
        logger.error(f"Edit player error: {str(e)}")
        flash('Napaka pri urejanju igralca', 'error')
        return redirect(url_for('admin_players'))

@app.route('/admin/players/<int:player_id>/delete', methods=['POST'])
@admin_required
@permission_required('manage_players')
def admin_delete_player(player_id):
    """Delete player"""
    try:
        player = database.get_player_by_id(player_id)
        if not player:
            flash('Igralec ni bil najden', 'error')
            return redirect(url_for('admin_players'))
        
        team_id = player['team_id']
        
        if database.delete_player(player_id):
            flash(f'Igralec {player["name"]} je bil uspešno odstranjen', 'success')
        else:
            flash('Napaka pri odstranjevanju igralca', 'error')
            
        return redirect(url_for('admin_team_players', team_id=team_id))
            
    except Exception as e:
        logger.error(f"Delete player error: {str(e)}")
        flash('Napaka pri odstranjevanju igralca', 'error')
        return redirect(url_for('admin_players'))

# === Match Results Routes ===
@app.route('/admin/match-results')
@admin_required
@permission_required('manage_results')
def admin_match_results():
    """List all matches with results"""
    try:
        matches = database.get_all_matches_for_results()
        return render_template('admin/match_results.html', matches=matches)
    except Exception as e:
        logger.error(f"Match results error: {str(e)}")
        flash('Napaka pri pridobivanju rezultatov tekem', 'error')
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/match-results/<string:match_id>/edit')
@admin_required
@permission_required('manage_results')
def admin_edit_match_result(match_id):
    """Edit match result details"""
    try:
        # Get match info
        match = database.get_match_by_unique_id(match_id)
        if not match:
            flash('Tekma ni bila najdena', 'error')
            return redirect(url_for('admin_match_results'))
        
        # Get or create match result
        result = None
        try:
            result = database.get_match_result_by_match_id(match_id)
        except:
            pass
        
        if not result:
            # Try to find team IDs by names
            home_team = database.find_team_by_name(match['home_team'], match['league_id'])
            away_team = database.find_team_by_name(match['away_team'], match['league_id'])
            
            if home_team and away_team:
                result_id = database.create_match_result(
                    match_id, home_team['id'], away_team['id'], 0, 0, 'scheduled'
                )
                result = database.get_match_result_by_id(result_id)
        
        if not result:
            flash('Ni mogoče ustvariti rezultata tekme - manjkajo podatki o ekipah', 'error')
            return redirect(url_for('admin_match_results'))
        
        # Get goals and cards
        goals = database.get_match_goals(result['id'])
        cards = database.get_match_cards(result['id'])
        
        # Get team players
        home_players = database.get_team_players(result['home_team_id']) if result['home_team_id'] else []
        away_players = database.get_team_players(result['away_team_id']) if result['away_team_id'] else []
        
        return render_template('admin/edit_match_result.html', 
                             match=match, result=result, goals=goals, cards=cards,
                             home_players=home_players, away_players=away_players)
    
    except Exception as e:
        logger.error(f"Edit match result error: {str(e)}")
        flash('Napaka pri urejanju rezultata tekme', 'error')
        return redirect(url_for('admin_match_results'))

@app.route('/admin/match-results/<int:result_id>/update', methods=['POST'])
@admin_required
@permission_required('manage_results')
def admin_update_match_result(result_id):
    """Update match result"""
    try:
        home_score = int(request.form.get('home_score', 0))
        away_score = int(request.form.get('away_score', 0))
        status = request.form.get('status', 'finished')
        referee = request.form.get('referee', '').strip() or None
        notes = request.form.get('notes', '').strip() or None
        
        if database.update_match_result(result_id, home_score, away_score, status, referee, notes):
            flash('Rezultat tekme je bil posodobljen', 'success')
        else:
            flash('Napaka pri posodabljanju rezultata', 'error')
            
    except Exception as e:
        logger.error(f"Update match result error: {str(e)}")
        flash('Napaka pri posodabljanju rezultata tekme', 'error')
    
    # Get match_id for redirect
    result = database.get_match_result_by_id(result_id)
    if result:
        return redirect(url_for('admin_edit_match_result', match_id=result['match_id']))
    return redirect(url_for('admin_match_results'))

# === Goals Routes ===
@app.route('/admin/match-results/<int:result_id>/goals/add', methods=['POST'])
@admin_required
@permission_required('manage_results')
def admin_add_goal(result_id):
    """Add goal to match"""
    try:
        player_id = int(request.form.get('player_id'))
        team_id = int(request.form.get('team_id'))
        minute = int(request.form.get('minute'))
        goal_type = request.form.get('goal_type', 'regular')
        assist_player_id = request.form.get('assist_player_id')
        assist_player_id = int(assist_player_id) if assist_player_id else None
        
        goal_id = database.add_goal(result_id, player_id, team_id, minute, goal_type, assist_player_id)
        if goal_id:
            flash('Gol je bil dodan', 'success')
        else:
            flash('Napaka pri dodajanju gola', 'error')
            
    except Exception as e:
        logger.error(f"Add goal error: {str(e)}")
        flash('Napaka pri dodajanju gola', 'error')
    
    # Get match_id for redirect
    result = database.get_match_result_by_id(result_id)
    if result:
        return redirect(url_for('admin_edit_match_result', match_id=result['match_id']))
    return redirect(url_for('admin_match_results'))

@app.route('/admin/goals/<int:goal_id>/delete', methods=['POST'])
@admin_required
@permission_required('manage_results')
def admin_delete_goal(goal_id):
    """Delete goal"""
    try:
        if database.delete_goal(goal_id):
            flash('Gol je bil odstranjen', 'success')
        else:
            flash('Napaka pri odstranjevanju gola', 'error')
    except Exception as e:
        logger.error(f"Delete goal error: {str(e)}")
        flash('Napaka pri odstranjevanju gola', 'error')
    
    return redirect(request.referrer or url_for('admin_match_results'))

# === Cards Routes ===
@app.route('/admin/match-results/<int:result_id>/cards/add', methods=['POST'])
@admin_required
@permission_required('manage_results')
def admin_add_card(result_id):
    """Add card to match"""
    try:
        player_id = int(request.form.get('player_id'))
        team_id = int(request.form.get('team_id'))
        card_type = request.form.get('card_type')
        minute = int(request.form.get('minute'))
        reason = request.form.get('reason', '').strip() or None
        
        card_id = database.add_card(result_id, player_id, team_id, card_type, minute, reason)
        if card_id:
            flash('Karton je bil dodan', 'success')
        else:
            flash('Napaka pri dodajanju kartona', 'error')
            
    except Exception as e:
        logger.error(f"Add card error: {str(e)}")
        flash('Napaka pri dodajanju kartona', 'error')
    
    # Get match_id for redirect
    result = database.get_match_result_by_id(result_id)
    if result:
        return redirect(url_for('admin_edit_match_result', match_id=result['match_id']))
    return redirect(url_for('admin_match_results'))

@app.route('/admin/cards/<int:card_id>/delete', methods=['POST'])
@admin_required
@permission_required('manage_results')
def admin_delete_card(card_id):
    """Delete card"""
    try:
        if database.delete_card(card_id):
            flash('Karton je bil odstranjen', 'success')
        else:
            flash('Napaka pri odstranjevanju kartona', 'error')
    except Exception as e:
        logger.error(f"Delete card error: {str(e)}")
        flash('Napaka pri odstranjevanju kartona', 'error')
    
    return redirect(request.referrer or url_for('admin_match_results'))

if __name__ == '__main__':
    database.init_db_pool()
    database.init_db()
    app.run(host='0.0.0.0', port=5000)
