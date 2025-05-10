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
        "results_url": urljoin(BASE_URL, "/index.php/ct-menu-item-7/razpored-liga-a"),
        "leaderboard_url_source": urljoin(BASE_URL, "/index.php/ct-menu-item-7/lestvica-liga-a")
    },
    "liga_b": {
        "name": "Liga B",
        "display_name": "Liga -B-",
        "results_url": urljoin(BASE_URL, "/index.php/2017-08-11-13-54-06/razpored-liga-b"),
        "leaderboard_url_source": urljoin(BASE_URL, "/index.php/2017-08-11-13-54-06/lestvica-liga-b")
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
    # ... (function remains the same)
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


# Define the results route more explicitly for POST actions
@app.route('/league/<league_id>/results', methods=['GET', 'POST'])
def show_league_results(league_id): # Renamed function for clarity
    if league_id not in LEAGUES_CONFIG:
        # Redirect to default league's results page if league_id is invalid
        return redirect(url_for('show_league_results', league_id=DEFAULT_LEAGUE_ID)) 
    
    current_league_config = LEAGUES_CONFIG[league_id]
    
    # Determine the URL to scrape for this request
    url_to_scrape_for_specific_round = current_league_config["results_url"] # Default to league's main results page

    if request.method == 'POST':
        # Ensure the form submission is for the current league
        if request.form.get('league_id_form_field') == league_id:
            form_selected_round_url = request.form.get('round_select_url')
            if form_selected_round_url:
                url_to_scrape_for_specific_round = form_selected_round_url
    elif request.args.get('round_url'): # Check for round_url in GET parameters
        url_to_scrape_for_specific_round = request.args.get('round_url')

    print(f"--- Route: show_league_results for {league_id} ---")
    print(f"URL to scrape for specific round data: {url_to_scrape_for_specific_round}")

    # 1. Get available rounds (cache or scrape)
    # Always fetch rounds list from the league's main results page to ensure consistency
    available_rounds = database.get_cached_rounds(league_id)
    if not available_rounds:
        print(f"No cached rounds for {league_id}, scraping from {current_league_config['results_url']}")
        _, _, scraped_rounds, _ = fetch_lmn_radgona_data(current_league_config["results_url"], fetch_all_rounds_data=False)
        if scraped_rounds:
            available_rounds = scraped_rounds
            database.cache_rounds(league_id, available_rounds)
        else:
            available_rounds = [] # Ensure it's a list

    # 2. Get matches for the specific round (cache or scrape)
    page_matches = database.get_cached_round_matches(league_id, url_to_scrape_for_specific_round)
    current_round_details_for_display = None

    if page_matches is None: # Cache miss or stale
        print(f"No cached/stale matches for {url_to_scrape_for_specific_round}, scraping.")
        scraped_page_matches, _, _, round_info_from_scrape = fetch_lmn_radgona_data(url_to_scrape_for_specific_round, fetch_all_rounds_data=False)
        if scraped_page_matches:
            page_matches = scraped_page_matches
            database.cache_matches(league_id, url_to_scrape_for_specific_round, page_matches)
            current_round_details_for_display = round_info_from_scrape
        else:
            page_matches = []
            current_round_details_for_display = {'name': 'Napaka pri nalaganju', 'url': url_to_scrape_for_specific_round}
            print(f"Failed to scrape matches for {url_to_scrape_for_specific_round}")
    else: # Matches found in cache
        # Find the round details for the cached matches (url_to_scrape_for_specific_round)
        if available_rounds:
            for r_opt in available_rounds:
                if r_opt['url'] == url_to_scrape_for_specific_round:
                    current_round_details_for_display = r_opt
                    break
        if not current_round_details_for_display: # Fallback if not in list
             current_round_details_for_display = {'name': 'Izbrani krog (iz predpomnilnika)', 'url': url_to_scrape_for_specific_round}


    grouped_data = {}
    if page_matches:
        for match in page_matches:
            date_key = match['date_str']
            if date_key not in grouped_data: grouped_data[date_key] = []
            grouped_data[date_key].append(match)
    
    page_title_main = f"LMN Radgona: {current_league_config['display_name']}"
    page_title_section = current_round_details_for_display.get('name', "Rezultati") if current_round_details_for_display else "Rezultati"
    
    # Ensure a sensible default if name is still "N/A"
    if page_title_section == "N/A" or ("krog" not in page_title_section.lower() and "rezultati" not in page_title_section.lower()):
        page_title_section = "Aktualni rezultati"


    return render_template('results_radgona.html', 
                           grouped_results=grouped_data,
                           all_rounds=available_rounds or [],
                           current_selected_url=url_to_scrape_for_specific_round, # This is the URL whose data is shown
                           page_title_main=page_title_main,
                           page_title_section=page_title_section,
                           source_url_for_data=url_to_scrape_for_specific_round,
                           today_date=datetime.now().date(),
                           current_league_id=league_id
                           )

# Root route now explicitly redirects to the default league's results page
@app.route('/', methods=['GET'])
def index():
    return redirect(url_for('show_league_results', league_id=DEFAULT_LEAGUE_ID))


@app.route('/league/<league_id>/leaderboard')
def show_leaderboard(league_id):
    if league_id not in LEAGUES_CONFIG:
        return redirect(url_for('show_leaderboard', league_id=DEFAULT_LEAGUE_ID))

    current_league_config = LEAGUES_CONFIG[league_id]
    leaderboard_data = database.get_cached_leaderboard(league_id)
    
    # We also need to check if the underlying match data in the DB is comprehensive enough or recent.
    # For simplicity now, if leaderboard cache is miss/stale, we re-fetch all matches.
    if leaderboard_data is None:
        print(f"Leaderboard cache miss/stale for {league_id}. Fetching all match data.")
        
        # This call will scrape all rounds. The scraper itself doesn't cache to DB per round in this version.
        # It returns a list of all matches found.
        _, scraped_all_matches, _, _ = fetch_lmn_radgona_data(
            current_league_config["results_url"], 
            fetch_all_rounds_data=True
            # league_id_for_caching=league_id # This param is for if scraper directly caches
        )

        if scraped_all_matches:
            print(f"Successfully scraped {len(scraped_all_matches)} total matches for {league_id} leaderboard.")
            # Now, we need to ensure these scraped matches are in our DB.
            # We can iterate and cache them by their original round_url.
            # Group matches by their 'round_url' to cache them efficiently.
            matches_by_round_url = defaultdict(list)
            for match in scraped_all_matches:
                if match.get('round_url'): # Make sure round_url is present
                    matches_by_round_url[match['round_url']].append(match)
            
            for r_url, r_matches in matches_by_round_url.items():
                database.cache_matches(league_id, r_url, r_matches)
            
            # After caching, retrieve all matches from the DB to ensure consistency
            all_matches_from_db = database.get_all_matches_for_league(league_id)
            leaderboard_data = calculate_leaderboard(all_matches_from_db)
            
            if leaderboard_data:
                database.cache_leaderboard(league_id, leaderboard_data)
            else:
                leaderboard_data = [] # Ensure it's a list if calculation yields nothing
                print(f"Leaderboard calculation resulted in empty data for {league_id} despite scraping.")
        else:
            print(f"Failed to scrape any matches for {league_id} leaderboard. Trying DB.")
            # Fallback to whatever is in the DB if scraping all failed
            all_matches_from_db = database.get_all_matches_for_league(league_id)
            leaderboard_data = calculate_leaderboard(all_matches_from_db)
            if leaderboard_data: # Still try to cache if DB had something
                 database.cache_leaderboard(league_id, leaderboard_data)
            else:
                leaderboard_data = []


    page_title_main = f"LMN Radgona: {current_league_config['display_name']}"
    page_title_section = "Lestvica"

    return render_template('leaderboard.html',
                           leaderboard_data=leaderboard_data,
                           page_title_main=page_title_main,
                           page_title_section=page_title_section,
                           current_league_id=league_id,
                           source_url_for_data=current_league_config["results_url"] 
                           )

if __name__ == '__main__':
    extra_dirs = ['templates',]
    extra_files = extra_dirs[:]
    for extra_dir in extra_dirs:
        for dirname, dirs, files in os.walk(extra_dir):
            for filename in files:
                filename = os.path.join(dirname, filename)
                if os.path.isfile(filename):
                    extra_files.append(filename)
    app.run(debug=True, extra_files=extra_files)