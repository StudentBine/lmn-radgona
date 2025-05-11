from flask import Flask, render_template, request, redirect, url_for
from flask_caching import Cache
from flask_compress import Compress
from scraper_radgona import fetch_lmn_radgona_data, BASE_URL, parse_score
from datetime import datetime
from urllib.parse import urljoin
from collections import defaultdict
import database

app = Flask(__name__)
Compress(app)
cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache'})

database.init_db_pool()
database.init_db()

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

def calculate_leaderboard(all_matches_for_league):
    if not all_matches_for_league:
        return []
    team_stats = defaultdict(lambda: {'played': 0, 'won': 0, 'drawn': 0, 'lost': 0,
                                      'goals_for': 0, 'goals_against': 0, 'goal_difference': 0,
                                      'points': 0, 'name': '', 'css_class': ''})
    for match in all_matches_for_league:
        home = match['home_team']
        away = match['away_team']
        score_str = match['score_str']
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
    leaderboard.sort(key=lambda x: x['name'])
    leaderboard.sort(key=lambda x: (x['points'], x['goal_difference'], x['goals_for']), reverse=True)

    # Add display class tags based on league-specific rules
    for i, team in enumerate(leaderboard):
        team['css_class'] = ''
    if leaderboard:
        if len(leaderboard) >= 2:
            if league_id == 'liga_a':
                leaderboard[-1]['css_class'] = 'last-place'
                leaderboard[-2]['css_class'] = 'last-place'
                leaderboard[0]['css_class'] = 'top-place'
            elif league_id == 'liga_b':
                leaderboard[0]['css_class'] = 'top-place'
                leaderboard[1]['css_class'] = 'top-place'

    return leaderboard

@app.route('/')
def index():
    return redirect(url_for('show_league_results', league_id=DEFAULT_LEAGUE_ID))

@cache.cached(timeout=300, query_string=True)
@app.route('/league/<league_id>/results', methods=['GET', 'POST'])
def show_league_results(league_id):
    if league_id not in LEAGUES_CONFIG:
        return redirect(url_for('show_league_results', league_id=DEFAULT_LEAGUE_ID))

    league_config = LEAGUES_CONFIG[league_id]
    target_round_url = league_config["main_results_page_url"]

    if request.method == 'POST' and request.form.get('league_id_form_field') == league_id:
        form_selected_url = request.form.get('round_select_url')
        if form_selected_url:
            target_round_url = form_selected_url
    elif request.args.get('round_url'):
        target_round_url = request.args.get('round_url')

    available_rounds = database.get_cached_rounds(league_id)
    initial_page_round_info = None

    if not available_rounds:
        _, _, scraped_rounds, scraped_initial = fetch_lmn_radgona_data(
            league_config["main_results_page_url"], fetch_all_rounds_data=False)
        if scraped_rounds:
            available_rounds = scraped_rounds
            initial_page_round_info = scraped_initial
            database.cache_rounds(league_id, scraped_rounds)
    else:
        if target_round_url == league_config["main_results_page_url"]:
            _, _, _, temp_initial = fetch_lmn_radgona_data(league_config["main_results_page_url"], False)
            initial_page_round_info = temp_initial

    if target_round_url == league_config["main_results_page_url"] and initial_page_round_info and initial_page_round_info.get('url'):
        target_round_url = initial_page_round_info['url']

    page_matches = database.get_cached_round_matches(league_id, target_round_url)
    round_details = next((r for r in available_rounds or [] if r['url'] == target_round_url), None)

    if page_matches is None:
        scraped_matches, _, _, scraped_round_info = fetch_lmn_radgona_data(
            target_round_url, fetch_all_rounds_data=False)
        if scraped_matches:
            database.cache_matches(league_id, target_round_url, scraped_matches)
            page_matches = scraped_matches
            round_details = scraped_round_info
        else:
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

@cache.cached(timeout=300)
@app.route('/league/<league_id>/leaderboard')
def show_leaderboard(league_id):
    if league_id not in LEAGUES_CONFIG:
        return redirect(url_for('show_leaderboard', league_id=DEFAULT_LEAGUE_ID))

    force_refresh = request.args.get('force', 'false').lower() == 'true'
    leaderboard_data = None if force_refresh else database.get_cached_leaderboard(league_id)

    if leaderboard_data is None or force_refresh:
        # Only update latest round instead of scraping all
        current_round_info = None
        rounds = database.get_cached_rounds(league_id)
        if not rounds:
            _, _, rounds, current_round_info = fetch_lmn_radgona_data(
                LEAGUES_CONFIG[league_id]['main_results_page_url'], fetch_all_rounds_data=False)
            if rounds:
                database.cache_rounds(league_id, rounds)
        if rounds:
            current_round_info = rounds[-1] if not current_round_info else current_round_info
            if database.get_cached_round_matches(league_id, current_round_info['url']) is None:
                scraped, _, _, _ = fetch_lmn_radgona_data(current_round_info['url'], fetch_all_rounds_data=False)
                if scraped:
                    database.cache_matches(league_id, current_round_info['url'], scraped)
        all_matches = database.get_all_matches_for_league(league_id)
        leaderboard_data = calculate_leaderboard(all_matches)
        if leaderboard_data:
            database.cache_leaderboard(league_id, leaderboard_data)

    # Ensure leaderboard has css_class keys if loaded from cache
    for i, team in enumerate(leaderboard_data):
        if 'css_class' not in team:
            team['css_class'] = ''
    if leaderboard_data:
        if len(leaderboard_data) >= 2:
            if league_id == 'liga_a':
                leaderboard_data[-1]['css_class'] = 'last-place'
                leaderboard_data[-2]['css_class'] = 'last-place'
                leaderboard_data[0]['css_class'] = 'top-place'
            elif league_id == 'liga_b':
                leaderboard_data[0]['css_class'] = 'top-place'
                leaderboard_data[1]['css_class'] = 'top-place'

    return render_template('leaderboard.html',
                           leaderboard_data=leaderboard_data,
                           page_title_main=f"LMN Radgona: {LEAGUES_CONFIG[league_id]['display_name']}",
                           page_title_section="Lestvica",
                           current_league_id=league_id,
                           source_url_for_data=LEAGUES_CONFIG[league_id]['main_results_page_url'])

if __name__ == '__main__':
    database.init_db_pool()
    database.init_db()
    app.run(host='0.0.0.0', port=5000)
