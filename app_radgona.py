from flask import Flask, render_template, request, redirect, url_for
from scraper_radgona import fetch_lmn_radgona_data, BASE_URL, parse_score
import os
from datetime import datetime
from urllib.parse import urljoin
from collections import defaultdict
import database

app = Flask(__name__)
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
                                      'points': 0, 'name': ''})
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
    return leaderboard

@app.route('/')
def index():
    return redirect(url_for('show_league_results', league_id=DEFAULT_LEAGUE_ID))

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
    round_details = None

    if page_matches is None:
        scraped_matches, _, _, scraped_round_info = fetch_lmn_radgona_data(
            target_round_url, fetch_all_rounds_data=False)
        if scraped_matches:
            database.cache_matches(league_id, target_round_url, scraped_matches)
            page_matches = scraped_matches
            round_details = scraped_round_info
        else:
            page_matches = []
            for r in available_rounds or []:
                if r['url'] == target_round_url:
                    round_details = r
                    break
            if not round_details:
                round_details = {'name': 'Napaka pri nalaganju', 'url': target_round_url}
    else:
        for r in available_rounds or []:
            if r['url'] == target_round_url:
                round_details = r
                break
        if not round_details:
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

@app.route('/league/<league_id>/leaderboard')
def show_leaderboard(league_id):
    if league_id not in LEAGUES_CONFIG:
        return redirect(url_for('show_leaderboard', league_id=DEFAULT_LEAGUE_ID))
    
    force_refresh = request.args.get('force', 'false').lower() == 'true'
    leaderboard_data = None if force_refresh else database.get_cached_leaderboard(league_id)

    if leaderboard_data is None:
        league_config = LEAGUES_CONFIG[league_id]
        all_rounds = database.get_cached_rounds(league_id)
        if not all_rounds:
            _, _, scraped_rounds, _ = fetch_lmn_radgona_data(league_config["main_results_page_url"], False)
            if scraped_rounds:
                all_rounds = scraped_rounds
                database.cache_rounds(league_id, scraped_rounds)

        for round_opt in all_rounds or []:
            try:
                cached = database.get_cached_round_matches(league_id, round_opt['url'])
                if cached is None:
                    scraped, _, _, _ = fetch_lmn_radgona_data(round_opt['url'], fetch_all_rounds_data=False)
                    if scraped:
                        database.cache_matches(league_id, round_opt['url'], scraped)
            except Exception as e:
                print(f"Napaka pri scrapingu kroga {round_opt['name']}: {e}")

        all_matches = database.get_all_matches_for_league(league_id)
        leaderboard_data = calculate_leaderboard(all_matches)
        if leaderboard_data:
            database.cache_leaderboard(league_id, leaderboard_data)

    return render_template('leaderboard.html',
                           leaderboard_data=leaderboard_data,
                           page_title_main=f"LMN Radgona: {LEAGUES_CONFIG[league_id]['display_name']}",
                           page_title_section="Lestvica",
                           current_league_id=league_id,
                           source_url_for_data=LEAGUES_CONFIG[league_id]['main_results_page_url'])

# --- Predcachiranje ---
def precache_all_leagues():
    print("== Začenjam predcachiranje vseh lig ==")
    for league_id, config in LEAGUES_CONFIG.items():
        print(f"\n-- Liga: {league_id} --")

        rounds = database.get_cached_rounds(league_id)
        if not rounds:
            print(f"Ni keširanih rund za {league_id}, scrapeam ...")
            _, _, scraped_rounds, _ = fetch_lmn_radgona_data(config['main_results_page_url'], fetch_all_rounds_data=False)
            if scraped_rounds:
                database.cache_rounds(league_id, scraped_rounds)
                rounds = scraped_rounds
                print(f"Shranjene runde ({len(rounds)}) za {league_id}")
            else:
                print(f"NAPAKA: Runde za {league_id} ni bilo mogoče pridobiti.")
                continue

        for i, round_opt in enumerate(rounds):
            url = round_opt['url']
            cached = database.get_cached_round_matches(league_id, url)
            if cached is None:
                print(f"  ({i+1}/{len(rounds)}) Scrapeam tekme za krog '{round_opt['name']}' ...")
                try:
                    matches, _, _, _ = fetch_lmn_radgona_data(url, fetch_all_rounds_data=False)
                    if matches:
                        database.cache_matches(league_id, url, matches)
                        print(f"    ✓ Shranjene {len(matches)} tekme.")
                    else:
                        print(f"    ✗ Ni najdenih tekem.")
                except Exception as e:
                    print(f"    ❌ Napaka pri scrapeanju: {e}")
            else:
                print(f"  ({i+1}/{len(rounds)}) Krog '{round_opt['name']}' že v kešu ({len(cached)} tekem).")
    print("== Predcachiranje zaključeno ==")

if __name__ == '__main__':
    database.init_db()
    precache_all_leagues()
    app.run(host='0.0.0.0', port=5000)
