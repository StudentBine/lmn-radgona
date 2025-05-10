from flask import Flask, render_template, request, redirect, url_for
from scraper_radgona import fetch_lmn_radgona_data, BASE_URL, parse_score
import os
from datetime import datetime, timedelta # timedelta needed for cache expiry
from urllib.parse import urljoin
from collections import defaultdict
import database_postgres as database

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
    # ... (function remains the same as before)
    if not all_matches_for_league: return []
    team_stats = defaultdict(lambda: {'played': 0, 'won': 0, 'drawn': 0, 'lost': 0,'goals_for': 0, 'goals_against': 0, 'goal_difference': 0,'points': 0, 'name': ''})
    for match in all_matches_for_league:
        home_team_name = match['home_team']
        away_team_name = match['away_team']
        score_str = match['score_str']
        if not team_stats[home_team_name]['name']: team_stats[home_team_name]['name'] = home_team_name
        if not team_stats[away_team_name]['name']: team_stats[away_team_name]['name'] = away_team_name
        home_goals, away_goals = parse_score(score_str)
        if home_goals is not None and away_goals is not None:
            team_stats[home_team_name]['played'] += 1
            team_stats[away_team_name]['played'] += 1
            team_stats[home_team_name]['goals_for'] += home_goals
            team_stats[home_team_name]['goals_against'] += away_goals
            team_stats[away_team_name]['goals_for'] += away_goals
            team_stats[away_team_name]['goals_against'] += home_goals
            if home_goals > away_goals:
                team_stats[home_team_name]['won'] += 1; team_stats[home_team_name]['points'] += 3
                team_stats[away_team_name]['lost'] += 1
            elif away_goals > home_goals:
                team_stats[away_team_name]['won'] += 1; team_stats[away_team_name]['points'] += 3
                team_stats[home_team_name]['lost'] += 1
            else:
                team_stats[home_team_name]['drawn'] += 1; team_stats[home_team_name]['points'] += 1
                team_stats[away_team_name]['drawn'] += 1; team_stats[away_team_name]['points'] += 1
    leaderboard = []
    for team_name, stats in team_stats.items():
        stats['goal_difference'] = stats['goals_for'] - stats['goals_against']
        leaderboard.append(stats)
    leaderboard.sort(key=lambda x: x['name'])
    leaderboard.sort(key=lambda x: (x['points'], x['goal_difference'], x['goals_for']), reverse=True)
    return leaderboard

@app.route('/', methods=['GET'])
def index():
    return redirect(url_for('show_league_results', league_id=DEFAULT_LEAGUE_ID))

@app.route('/league/<league_id>/results', methods=['GET', 'POST'])
def show_league_results(league_id):
    if league_id not in LEAGUES_CONFIG:
        return redirect(url_for('show_league_results', league_id=DEFAULT_LEAGUE_ID))
    
    current_league_config = LEAGUES_CONFIG[league_id]
    
    # Determine the target URL for which matches should be displayed
    # This will be the URL used for pre-selecting the dropdown as well.
    target_round_url = current_league_config["main_results_page_url"] # Default

    if request.method == 'POST' and request.form.get('league_id_form_field') == league_id:
        form_selected_url = request.form.get('round_select_url')
        if form_selected_url:
            target_round_url = form_selected_url
    elif request.args.get('round_url'):
        target_round_url = request.args.get('round_url')

    print(f"--- Route: show_league_results for {league_id} ---")
    print(f"Target round URL for display: {target_round_url}")

    # 1. Get/Update the list of all available rounds for this league
    available_rounds = database.get_cached_rounds(league_id)
    # `initial_page_round_info` is the round info (name, url, id) that is selected by default
    # on the LMN Radgona site's main results page for this league.
    initial_page_round_info = None 

    if not available_rounds: # Or if you want to refresh it periodically
        print(f"Rounds cache miss/stale for {league_id}. Scraping {current_league_config['main_results_page_url']} for rounds list.")
        _, _, scraped_available_rounds, scraped_initial_round_info = fetch_lmn_radgona_data(
            current_league_config["main_results_page_url"], 
            fetch_all_rounds_data=False # We only need rounds list and current selection from this page
        )
        if scraped_available_rounds:
            available_rounds = scraped_available_rounds
            database.cache_rounds(league_id, available_rounds)
            initial_page_round_info = scraped_initial_round_info
            print(f"Cached {len(available_rounds)} rounds for {league_id}. LMN Default round: {initial_page_round_info.get('name') if initial_page_round_info else 'N/A'}")
        else:
            available_rounds = []
            print(f"Failed to scrape available rounds for {league_id}.")
    else: # Rounds were cached. We might still want to know the current default on LMN.
          # For simplicity now, if it's an initial display (target_round_url is main page),
          # we'll use the 'selected' round from when we last cached available_rounds.
          # To get the *absolute latest* default from LMN, we'd need to scrape main_results_page_url again.
        if target_round_url == current_league_config["main_results_page_url"]:
            # Find the 'selected' one from the initial scrape that populated available_rounds
            # The scraper's extract_round_options_and_current returns the selected one.
            # We need to store this 'selected_on_lmn_default_page_url' when caching rounds.
            # For now, we re-fetch to get the current default on LMN:
            print(f"Getting current default selection from LMN for {league_id}")
            _, _, _, temp_initial_round_info = fetch_lmn_radgona_data(current_league_config["main_results_page_url"], False)
            initial_page_round_info = temp_initial_round_info


    # If this is an initial load of the league's page (not a specific round selection by user),
    # then the target_round_url should become the one LMN site defaults to.
    if target_round_url == current_league_config["main_results_page_url"] and initial_page_round_info and initial_page_round_info.get('url'):
        target_round_url = initial_page_round_info['url']
        print(f"Initial load of league page, updated target_round_url to LMN default: {target_round_url}")


    # 2. Get/Update matches for the target_round_url
    page_matches = database.get_cached_round_matches(league_id, target_round_url)
    round_details_of_displayed_data = None # Info about the round whose matches are being shown

    if page_matches is None: # Cache miss or stale for this specific round's matches
        print(f"Matches cache miss/stale for {target_round_url}. Scraping.")
        scraped_page_matches, _, _, scraped_round_info = fetch_lmn_radgona_data(
            target_round_url, 
            fetch_all_rounds_data=False # Only fetch for this specific round
        )
        if scraped_page_matches:
            page_matches = scraped_page_matches
            database.cache_matches(league_id, target_round_url, page_matches) # Cache these specific round matches
            round_details_of_displayed_data = scraped_round_info # Use info from the actual scrape
            print(f"Scraped and cached {len(page_matches)} matches for {round_details_of_displayed_data.get('name')}")
        else:
            page_matches = []
            # Try to get round name from available_rounds if scrape failed for matches
            if available_rounds:
                for r_opt in available_rounds:
                    if r_opt['url'] == target_round_url:
                        round_details_of_displayed_data = r_opt
                        break
            if not round_details_of_displayed_data:
                 round_details_of_displayed_data = {'name': 'Napaka pri nalaganju', 'url': target_round_url}
            print(f"Failed to scrape matches for {target_round_url}")
    else: # Matches found in cache
        print(f"Loaded {len(page_matches)} matches from cache for {target_round_url}")
        # Get the round name for display from the available_rounds list
        if available_rounds:
            for r_opt in available_rounds:
                if r_opt['url'] == target_round_url:
                    round_details_of_displayed_data = r_opt
                    break
        if not round_details_of_displayed_data: # Fallback if URL not in list (should not happen if available_rounds is good)
            round_details_of_displayed_data = {'name': 'Krog (iz predpomn.)', 'url': target_round_url}

    grouped_data = defaultdict(list)
    if page_matches:
        for match in page_matches:
            grouped_data[match['date_str']].append(match)
    
    page_title_main = f"LMN Radgona: {current_league_config['display_name']}"
    page_title_section = round_details_of_displayed_data.get('name', "Rezultati") if round_details_of_displayed_data else "Rezultati"
    if page_title_section == "N/A" or ("krog" not in page_title_section.lower()):
        page_title_section = "Aktualni rezultati" if not page_matches else page_title_section


    return render_template('results_radgona.html', 
                           grouped_results=dict(grouped_data), # Convert back to dict for template
                           all_rounds=available_rounds or [],
                           current_selected_url=target_round_url, # This URL's data is shown, so it's the selected one
                           page_title_main=page_title_main,
                           page_title_section=page_title_section,
                           source_url_for_data=target_round_url,
                           today_date=datetime.now().date(),
                           current_league_id=league_id
                           )

@app.route('/league/<league_id>/leaderboard')
def show_leaderboard(league_id):
    if league_id not in LEAGUES_CONFIG:
        return redirect(url_for('show_leaderboard', league_id=DEFAULT_LEAGUE_ID))

    current_league_config = LEAGUES_CONFIG[league_id]
    leaderboard_data = database.get_cached_leaderboard(league_id)

    if leaderboard_data is None:
        print(f"Leaderboard cache miss/stale for {league_id}. Preparing to calculate.")
        
        # Step 1: Get the list of all rounds for the league
        all_db_rounds = database.get_cached_rounds(league_id)
        if not all_db_rounds:
            print(f"NO ROUNDS IN CACHE for {league_id}. Scraping main league page for rounds list.")
            _, _, all_db_rounds, _ = fetch_lmn_radgona_data(current_league_config["main_results_page_url"], fetch_all_rounds_data=False)
            if all_db_rounds: 
                database.cache_rounds(league_id, all_db_rounds)
                print(f"Cached {len(all_db_rounds)} rounds for {league_id}.")
            else: 
                all_db_rounds = []
                print(f"CRITICAL: FAILED to get rounds for {league_id}. Leaderboard cannot be built.")
        
        # Step 2: Ensure matches for all these rounds are scraped and cached
        if all_db_rounds:
            print(f"Ensuring matches are cached for all {len(all_db_rounds)} rounds of {league_id}...")
            for i, round_opt in enumerate(all_db_rounds):
                # Check cache first for this specific round's matches
                cached_matches_for_this_round = database.get_cached_round_matches(league_id, round_opt['url'])
                if cached_matches_for_this_round is None: # Cache miss or stale for this round
                    if league_id == "liga_a":
                        print(f"  LIGA_A DEBUG: ({i+1}/{len(all_db_rounds)}) Matches for '{round_opt['name']}' NOT IN CACHE or STALE. Scraping: {round_opt['url']}")
                    
                    scraped_matches, _, _, _ = fetch_lmn_radgona_data(round_opt['url'], fetch_all_rounds_data=False)
                    if scraped_matches:
                        if league_id == "liga_a":
                             print(f"    LIGA_A DEBUG: Scraped {len(scraped_matches)} matches for '{round_opt['name']}'. Caching.")
                        database.cache_matches(league_id, round_opt['url'], scraped_matches)
                    elif league_id == "liga_a":
                        print(f"    LIGA_A DEBUG: FAILED to scrape matches for '{round_opt['name']}'.")
                elif league_id == "liga_a":
                     print(f"  LIGA_A DEBUG: ({i+1}/{len(all_db_rounds)}) Matches for '{round_opt['name']}' found fresh in cache ({len(cached_matches_for_this_round)} matches).")
        
        # Step 3: Now, get all matches from the DB (which should be populated/updated)
        all_matches_for_league = database.get_all_matches_for_league(league_id)
        if league_id == "liga_a":
            print(f"LIGA_A DEBUG: Total matches retrieved from DB for calculation: {len(all_matches_for_league)}")
            if all_matches_for_league:
                # Print a few samples to check their structure and scores, especially for Liga A
                for idx, m in enumerate(all_matches_for_league):
                    if idx < 5 or (len(all_matches_for_league) - idx) <= 2 : # First 5 and last 2
                        print(f"  LIGA_A DB Sample {idx}: R='{m.get('round_name')}', Date='{m.get('date_str')}', {m['home_team']} '{m['score_str']}' {m['away_team']}")
            else:
                print(f"LIGA_A DEBUG: No matches retrieved from DB for calculation. Leaderboard will be empty.")
        
        leaderboard_data = calculate_leaderboard(all_matches_for_league)
        if leaderboard_data:
            if league_id == "liga_a":
                print(f"LIGA_A DEBUG: Calculated leaderboard with {len(leaderboard_data)} teams.")
                # print(f"LIGA_A DEBUG: Sample team data: {leaderboard_data[0]}")
            database.cache_leaderboard(league_id, leaderboard_data)
        else:
            leaderboard_data = []
            if league_id == "liga_a":
                print(f"LIGA_A DEBUG: Leaderboard calculation resulted in empty data (all zeros expected).")

    else: # Leaderboard was found in cache
        if league_id == "liga_a":
            print(f"LIGA_A DEBUG: Using cached leaderboard with {len(leaderboard_data)} teams.")


    page_title_main = f"LMN Radgona: {current_league_config['display_name']}"
    page_title_section = "Lestvica"

    return render_template('leaderboard.html',
                           leaderboard_data=leaderboard_data,
                           page_title_main=page_title_main,
                           page_title_section=page_title_section,
                           current_league_id=league_id,
                           source_url_for_data=current_league_config["main_results_page_url"]
                           )

if __name__ == '__main__':
    database.init_db()
    app.run(host='0.0.0.0', port=5000)