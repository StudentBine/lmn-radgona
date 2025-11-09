from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, abort
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


@cache.cached(timeout=180, query_string=True)  # Reduced cache time for faster updates
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

        available_rounds = database.get_cached_rounds(league_id) or []
        
        # Speed optimization: Use cached data primarily, minimal scraping
        scraping_enabled = os.environ.get('ENABLE_SCRAPING', 'false').lower() == 'true'
        
        # Try to determine current round from cached data first
        current_round_from_cache = None
        if available_rounds:
            # Find the latest round with matches
            all_matches = database.get_all_matches_for_league(league_id) or []
            if all_matches:
                # Get the most recent round from matches
                latest_matches = sorted(all_matches, key=lambda x: x.get('date_obj') or datetime.now().date(), reverse=True)[:5]
                if latest_matches:
                    recent_round_name = latest_matches[0].get('round_name')
                    current_round_from_cache = next((r for r in available_rounds if r.get('name') == recent_round_name), None)
        
        # If no cached rounds and scraping enabled, try to get them
        if not available_rounds and scraping_enabled:
            try:
                _, _, scraped_rounds, scraped_initial = fetch_lmn_radgona_data(
                    league_config["main_results_page_url"], fetch_all_rounds_data=False, league_id_for_caching=league_id)
                if scraped_rounds:
                    available_rounds = scraped_rounds
                    database.cache_rounds(league_id, scraped_rounds)
                    logger.info(f"Successfully scraped {len(scraped_rounds)} rounds for {league_id}")
                    current_round_from_cache = scraped_initial
            except Exception as scrape_error:
                logger.warning(f"Failed to scrape rounds for {league_id}: {scrape_error}")
                available_rounds = []
        
        # Determine target URL - prefer current round or use requested URL
        if target_round_url == league_config["main_results_page_url"]:
            if current_round_from_cache and current_round_from_cache.get('url'):
                target_round_url = current_round_from_cache['url']
                logger.info(f"Using current round URL: {target_round_url}")

        # Get round details
        round_details = next((r for r in available_rounds if r.get('url') == target_round_url), None)
        if not round_details and current_round_from_cache:
            round_details = current_round_from_cache
        
        # Try to get cached matches for this specific round
        page_matches = database.get_cached_round_matches(league_id, target_round_url)

        # If cache is stale/expired, fallback to filtering all matches by round name
        if page_matches is None and round_details and round_details.get('name'):
            logger.info(f"Cache stale for {target_round_url}, filtering all matches by round name")
            all_league_matches = database.get_all_matches_for_league(league_id)
            if all_league_matches:
                round_name = round_details['name']
                page_matches = [m for m in all_league_matches if m.get('round_name') == round_name]
                logger.info(f"Found {len(page_matches)} matches for round '{round_name}' using fallback")
            
        if page_matches is None:
            # Check if scraping is disabled in production (default to disabled for safety)
            scraping_enabled = os.environ.get('ENABLE_SCRAPING', 'false').lower() == 'true'
            
            if scraping_enabled:
                try:
                    # Add timeout protection for web requests
                    import signal
                    
                    def timeout_handler(signum, frame):
                        raise TimeoutError("Scraping timeout - using cached data")
                    
                    # Set a 10 second timeout for scraping in web context
                    signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(10)
                    
                    try:
                        scraped_matches, _, _, scraped_round_info = fetch_lmn_radgona_data(
                            target_round_url, fetch_all_rounds_data=False, league_id_for_caching=league_id)
                        signal.alarm(0)  # Cancel timeout
                        
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
                    except TimeoutError as te:
                        signal.alarm(0)  # Cancel timeout
                        logger.warning(f"Scraping timeout for {target_round_url}: {te}")
                        page_matches = []
                        if not round_details:
                            round_details = {'name': 'Časovna omejitev', 'url': target_round_url}
                        
                except Exception as scrape_error:
                    try:
                        signal.alarm(0)  # Cancel timeout if still active
                    except:
                        pass
                    
                    if "415" in str(scrape_error) or "Unsupported Media Type" in str(scrape_error):
                        logger.warning(f"Server blocking detected (415) for {target_round_url}, using cached data only")
                    elif "Cloudflare" in str(scrape_error):
                        logger.warning(f"Cloudflare blocking detected for round {target_round_url}, using cached data only")
                    else:
                        logger.error(f"Failed to scrape matches for {target_round_url}: {scrape_error}")
                    page_matches = []
                    if not round_details:
                        round_details = {'name': 'Napaka pri nalaganju', 'url': target_round_url}
            else:
                logger.info(f"Scraping disabled, using cached data only for {target_round_url}")
                # Try to get any available matches from the league instead of empty list
                all_league_matches = database.get_all_matches_for_league(league_id)
                if all_league_matches:
                    # Filter matches for the current round if possible, otherwise show recent matches
                    if round_details and round_details.get('name'):
                        page_matches = [m for m in all_league_matches if m.get('round_name') == round_details['name']]
                    if not page_matches:
                        # Show the most recent matches (last 10) if no specific round matches
                        page_matches = all_league_matches[-10:] if len(all_league_matches) > 10 else all_league_matches
                    logger.info(f"Using {len(page_matches)} cached matches for {league_id}")
                else:
                    page_matches = []
                if not round_details:
                    round_details = {'name': 'Predpomnjeni podatki', 'url': target_round_url}
        elif not round_details:
            round_details = {'name': 'Krog (iz predpomn.)', 'url': target_round_url}
        
        # Final fallback: if still no page_matches, try to get any matches for the league
        if not page_matches:
            fallback_matches = database.get_all_matches_for_league(league_id)
            if fallback_matches:
                # Show the most recent matches
                page_matches = fallback_matches[-6:] if len(fallback_matches) > 6 else fallback_matches
                logger.info(f"Using {len(page_matches)} fallback matches for {league_id}")
                if not round_details:
                    round_details = {'name': 'Zadnje tekme', 'url': target_round_url}
                else:
                    round_details['name'] = f"Zadnje tekme ({round_details.get('name', 'neznano')})"

        # Filter matches based on winter break logic
        from datetime import date
        today = date.today()
        winter_break_start = date(2025, 11, 10)  # Winter break starts after round 13 
        season_restart = date(2026, 3, 1)        # Season restarts in March
        
        filtered_matches = []
        for match in page_matches:
            match_date = match.get('date_obj')
            round_name = match.get('round_name', '')
            
            # Winter break logic: Hide future rounds after round 13 during break period
            is_winter_break_period = today >= winter_break_start and today < season_restart
            
            if is_winter_break_period:
                # Extract round number
                round_num = None
                if 'krog' in round_name:
                    try:
                        round_num = int(round_name.split('.')[0])
                    except:
                        round_num = None
                
                # Skip rounds after 13 during winter break (rounds 14+)
                if round_num and round_num > 13:
                    continue
                    
                # Also skip unplayed matches in current period if date is in future
                if match_date and match_date > today and match.get('score_str') == 'N/P':
                    continue
            
            filtered_matches.append(match)
        
        grouped_data = defaultdict(list)
        for match in filtered_matches:
            grouped_data[match['date_str']].append(match)
            
        # If no matches after filtering, show a message about winter break
        if not filtered_matches and page_matches:
            logger.info(f"All matches filtered due to winter break period for {league_id}")
            # Create a placeholder to show winter break message
            grouped_data['Winter Break'] = [{
                'home_team': 'Winter Break',
                'away_team': 'Season Break',
                'score_str': 'PAUSE',
                'time': '',
                'venue': 'League suspended until March 2026'
            }]

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
            # Fast leaderboard loading - use cached data only
        logger.info(f"Loading leaderboard for {league_id} from cached data")
        all_matches = database.get_all_matches_for_league(league_id)
        if not all_matches:
            logger.warning(f"No cached data available for {league_id}")
            all_matches = []
            
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

@app.route('/api/match-details/<league_id>/<path:match_unique_id>')
def get_match_details_api(league_id, match_unique_id):
    """API endpoint to get match details (goals and cards)"""
    try:
        if league_id not in LEAGUES_CONFIG:
            return jsonify({'error': 'Invalid league ID'}), 404
        
        # Get match details from database
        match_details = database.get_match_details(match_unique_id, league_id)
        
        if not match_details:
            return jsonify({'error': 'Match not found'}), 404
        
        # Format the response
        response = {
            'match': {
                'home_team': match_details['match']['home_team'],
                'away_team': match_details['match']['away_team'],
                'score': match_details['match']['score_str'],
                'date': match_details['match']['date_str'],
                'time': match_details['match']['time'],
                'venue': match_details['match']['venue']
            },
            'goals': {
                'home': [
                    {
                        'player': g['player_name'],
                        'jersey_number': g.get('jersey_number'),
                        'minute': g.get('minute'),
                        'type': g.get('goal_type', 'regular'),
                        'assist': g.get('assist_player_name')
                    }
                    for g in match_details['goals']['home']
                ],
                'away': [
                    {
                        'player': g['player_name'],
                        'jersey_number': g.get('jersey_number'),
                        'minute': g.get('minute'),
                        'type': g.get('goal_type', 'regular'),
                        'assist': g.get('assist_player_name')
                    }
                    for g in match_details['goals']['away']
                ]
            },
            'cards': {
                'home': [
                    {
                        'player': c['player_name'],
                        'jersey_number': c.get('jersey_number'),
                        'card_type': c['card_type'],
                        'minute': c.get('minute'),
                        'reason': c.get('reason')
                    }
                    for c in match_details['cards']['home']
                ],
                'away': [
                    {
                        'player': c['player_name'],
                        'jersey_number': c.get('jersey_number'),
                        'card_type': c['card_type'],
                        'minute': c.get('minute'),
                        'reason': c.get('reason')
                    }
                    for c in match_details['cards']['away']
                ]
            },
            'has_details': len(match_details['goals']['home']) > 0 or len(match_details['goals']['away']) > 0 or 
                          len(match_details['cards']['home']) > 0 or len(match_details['cards']['away']) > 0
        }
        
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Error getting match details for {match_unique_id}: {str(e)}")
        return jsonify({'error': 'Internal server error', 'message': str(e)}), 500

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
            'scraper_max_workers': os.environ.get('SCRAPER_MAX_WORKERS', '3'),
            'enable_scraping': os.environ.get('ENABLE_SCRAPING', 'true'),
            'flask_env': os.environ.get('FLASK_ENV', 'development'),
            'port': os.environ.get('PORT', '5000'),
            'redis_configured': bool(os.environ.get('REDIS_URL'))
        }
        return f"<pre>{json.dumps(env_info, indent=2)}</pre>"
    except Exception as e:
        return f"<pre>Error: {str(e)}</pre>", 500

@app.route('/admin/toggle-scraping')
def toggle_scraping():
    """Toggle scraping on/off (temporary for this session)"""
    try:
        current_status = os.environ.get('ENABLE_SCRAPING', 'false').lower() == 'true'  # Default to false
        new_status = 'false' if current_status else 'true'
        
        # This only affects the current process, not persistent
        os.environ['ENABLE_SCRAPING'] = new_status
        
        status_text = 'enabled' if new_status == 'true' else 'disabled'
        return f"<h2>Scraping {status_text}</h2><p>Current session only - will reset on restart</p><p><a href='/admin/env-check'>Check Environment</a></p><p><a href='/admin/status'>App Status</a></p>"
        
    except Exception as e:
        return f"<pre>Error: {str(e)}</pre>", 500

@app.route('/admin/status')
def admin_status():
    """Show current application status"""
    try:
        scraping_enabled = os.environ.get('ENABLE_SCRAPING', 'false').lower() == 'true'
        is_production = os.environ.get('FLASK_ENV', 'development') == 'production'
        
        # Get some stats from database
        try:
            liga_a_matches = database.get_all_matches_for_league('liga_a') or []
            liga_b_matches = database.get_all_matches_for_league('liga_b') or []
            liga_a_leaderboard = database.get_cached_leaderboard('liga_a')
            liga_b_leaderboard = database.get_cached_leaderboard('liga_b')
            liga_a_rounds = database.get_cached_rounds('liga_a') or []
            liga_b_rounds = database.get_cached_rounds('liga_b') or []
        except Exception as e:
            logger.error(f"Error getting status data: {e}")
            liga_a_matches = liga_b_matches = []
            liga_a_leaderboard = liga_b_leaderboard = None
            liga_a_rounds = liga_b_rounds = []
        
        status_info = {
            'timestamp': datetime.now().isoformat(),
            'scraping_enabled': scraping_enabled,
            'is_production': is_production,
            'effective_scraping': scraping_enabled and not is_production,
            'cached_data': {
                'liga_a_matches': len(liga_a_matches),
                'liga_b_matches': len(liga_b_matches),
                'liga_a_rounds': len(liga_a_rounds),
                'liga_b_rounds': len(liga_b_rounds),
                'liga_a_leaderboard_teams': len(liga_a_leaderboard) if liga_a_leaderboard else 0,
                'liga_b_leaderboard_teams': len(liga_b_leaderboard) if liga_b_leaderboard else 0,
                'sample_liga_a_matches': [
                    f"{m.get('round_name', 'N/A')}: {m.get('home_team', 'N/A')} vs {m.get('away_team', 'N/A')} ({m.get('score_str', 'N/A')})"
                    for m in liga_a_matches[-3:]
                ] if liga_a_matches else []
            }
        }
        
        html = f"""
        <h2>Application Status</h2>
        <pre>{json.dumps(status_info, indent=2, default=str)}</pre>
        <h3>Quick Actions</h3>
        <p><a href="/admin/toggle-scraping">Toggle Scraping</a></p>
        <p><a href="/admin/env-check">Environment Check</a></p>
        <p><a href="/admin/clear-cache/liga_a">Clear Liga A Cache</a></p>
        <p><a href="/admin/clear-cache/liga_b">Clear Liga B Cache</a></p>
        <p><a href="/league/liga_a/results">Liga A Results</a></p>
        <p><a href="/league/liga_b/results">Liga B Results</a></p>
        <p><a href="/league/liga_a/leaderboard">Liga A Leaderboard</a></p>
        <p><a href="/league/liga_b/leaderboard">Liga B Leaderboard</a></p>
        """
        
        return html
        
    except Exception as e:
        return f"<pre>Error: {str(e)}</pre>", 500

@app.route('/admin/winter-break-status')
def winter_break_status():
    """Check winter break status and match filtering"""
    try:
        from datetime import date
        today = date.today()
        winter_break_start = date(2025, 11, 10)
        season_restart = date(2026, 3, 1)
        
        is_winter_break = today >= winter_break_start and today < season_restart
        
        status = {
            'current_date': today.isoformat(),
            'winter_break_start': winter_break_start.isoformat(),
            'season_restart': season_restart.isoformat(),
            'is_winter_break_period': is_winter_break,
            'days_until_break': (winter_break_start - today).days if today < winter_break_start else 0,
            'days_until_restart': (season_restart - today).days if today < season_restart else 0
        }
        
        # Check how many matches would be filtered for each league
        for league_id in ['liga_a', 'liga_b']:
            matches = database.get_all_matches_for_league(league_id) or []
            total_matches = len(matches)
            filtered_matches = 0
            
            for match in matches:
                round_name = match.get('round_name', '')
                match_date = match.get('date_obj')
                
                round_num = None
                if 'krog' in round_name:
                    try:
                        round_num = int(round_name.split('.')[0])
                    except:
                        pass
                
                if is_winter_break:
                    if round_num and round_num > 13:
                        filtered_matches += 1
                    elif match_date and match_date > today and match.get('score_str') == 'N/P':
                        filtered_matches += 1
            
            status[f'{league_id}_total_matches'] = total_matches
            status[f'{league_id}_filtered_matches'] = filtered_matches
            status[f'{league_id}_shown_matches'] = total_matches - filtered_matches
        
        html = f"""
        <h2>Winter Break Status</h2>
        <pre>{json.dumps(status, indent=2, default=str)}</pre>
        <h3>Actions</h3>
        <p><a href="/admin/status">Back to Admin Status</a></p>
        <p><a href="/league/liga_a/results">Liga A Results</a></p>
        <p><a href="/league/liga_b/results">Liga B Results</a></p>
        """
        
        return html
        
    except Exception as e:
        return f"<pre>Error: {str(e)}</pre>", 500

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

# ============================================================
# ERROR HANDLERS
# ============================================================

# Test endpoints for error pages (only in development)
@app.route('/test-error/<int:code>')
def test_error(code):
    """Test endpoint to preview error pages - Remove in production!"""
    if os.environ.get('FLASK_ENV') == 'production':
        abort(404)
    
    error_messages = {
        400: 'Napačen zahtevek. Prosimo preverite vnesene podatke.',
        403: 'Nimate dovoljenja za dostop do te strani.',
        404: None,  # Will use default message from template
        500: None,  # Will use default message from template
        503: 'Storitev trenutno ni na voljo. Poskusite znova čez nekaj trenutkov.'
    }
    
    return render_template('error.html',
                         error_code=code,
                         error_message=error_messages.get(code)), code

@app.errorhandler(404)
def page_not_found(e):
    """Handle 404 - Page Not Found errors"""
    logger.warning(f"404 error: {request.url}")
    
    # Check if it's an API request - only return JSON if explicitly requested
    if request.path.startswith('/api/') or (request.accept_mimetypes.best == 'application/json'):
        return jsonify({
            'error': 'Not Found',
            'message': 'The requested resource was not found',
            'code': 404
        }), 404
    
    return render_template('error.html', 
                         error_code=404,
                         error_message=None), 404

@app.errorhandler(403)
def forbidden(e):
    """Handle 403 - Forbidden errors"""
    logger.warning(f"403 error: {request.url}")
    
    if request.path.startswith('/api/') or (request.accept_mimetypes.best == 'application/json'):
        return jsonify({
            'error': 'Forbidden',
            'message': 'You do not have permission to access this resource',
            'code': 403
        }), 403
    
    return render_template('error.html',
                         error_code=403,
                         error_message='Nimate dovoljenja za dostop do te strani.'), 403

@app.errorhandler(500)
def internal_server_error(e):
    """Handle 500 - Internal Server Error"""
    logger.error(f"500 error: {request.url} - {str(e)}")
    
    if request.path.startswith('/api/') or (request.accept_mimetypes.best == 'application/json'):
        return jsonify({
            'error': 'Internal Server Error',
            'message': 'An unexpected error occurred on the server',
            'code': 500
        }), 500
    
    return render_template('error.html',
                         error_code=500,
                         error_message=None), 500

@app.errorhandler(503)
def service_unavailable(e):
    """Handle 503 - Service Unavailable"""
    logger.error(f"503 error: {request.url}")
    
    if request.path.startswith('/api/') or (request.accept_mimetypes.best == 'application/json'):
        return jsonify({
            'error': 'Service Unavailable',
            'message': 'The service is temporarily unavailable',
            'code': 503
        }), 503
    
    return render_template('error.html',
                         error_code=503,
                         error_message='Storitev trenutno ni na voljo. Poskusite znova čez nekaj trenutkov.'), 503

@app.errorhandler(400)
def bad_request(e):
    """Handle 400 - Bad Request"""
    logger.warning(f"400 error: {request.url} - {str(e)}")
    
    if request.path.startswith('/api/') or (request.accept_mimetypes.best == 'application/json'):
        return jsonify({
            'error': 'Bad Request',
            'message': 'The request was invalid or cannot be processed',
            'code': 400
        }), 400
    
    return render_template('error.html',
                         error_code=400,
                         error_message='Napačen zahtevek. Prosimo preverite vnesene podatke.'), 400

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    """Handle any unexpected errors"""
    logger.error(f"Unexpected error: {request.url} - {str(e)}", exc_info=True)
    
    # Don't catch errors in debug mode
    if app.debug:
        raise e
    
    if request.path.startswith('/api/') or (request.accept_mimetypes.best == 'application/json'):
        return jsonify({
            'error': 'Internal Server Error',
            'message': 'An unexpected error occurred',
            'code': 500
        }), 500
    
    return render_template('error.html',
                         error_code=500,
                         error_message='Prišlo je do nepričakovane napake. Poskusite ponovno.'), 500

# ============================================================
# APPLICATION STARTUP
# ============================================================

if __name__ == '__main__':
    database.init_db_pool()
    database.init_db()
    app.run(host='0.0.0.0', port=5000)
