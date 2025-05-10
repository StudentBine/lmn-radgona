from flask import Flask, render_template, request, redirect, url_for
from scraper_radgona import fetch_lmn_radgona_data, BASE_URL, parse_score # Import parse_score
import os
from datetime import datetime
from urllib.parse import urljoin
from collections import defaultdict

app = Flask(__name__)

LEAGUES_CONFIG = {
    "liga_a": {
        "name": "Liga A",
        "display_name": "Liga -A-",
        "results_url": urljoin(BASE_URL, "/index.php/ct-menu-item-7/razpored-liga-a"),
        "leaderboard_url": urljoin(BASE_URL, "/index.php/ct-menu-item-7/lestvica-liga-a") # Original leaderboard URL for reference
    },
    "liga_b": {
        "name": "Liga B",
        "display_name": "Liga -B-",
        "results_url": urljoin(BASE_URL, "/index.php/2017-08-11-13-54-06/razpored-liga-b"),
        "leaderboard_url": urljoin(BASE_URL, "/index.php/2017-08-11-13-54-06/lestvica-liga-b")
    }
}
DEFAULT_LEAGUE_ID = "liga_a"


def calculate_leaderboard(all_matches):
    """
    Calculates leaderboard stats from a list of all match data.
    Assumes standard 3 points for a win, 1 for a draw.
    """
    if not all_matches:
        return []

    # Initialize stats for each team
    # Using defaultdict to easily add new teams
    team_stats = defaultdict(lambda: {
        'played': 0, 'won': 0, 'drawn': 0, 'lost': 0,
        'goals_for': 0, 'goals_against': 0, 'goal_difference': 0,
        'points': 0, 'name': '' # Team name will be set once
    })

    for match in all_matches:
        home_team_name = match['home_team']
        away_team_name = match['away_team']
        score_str = match['score_str']

        # Initialize team names if not already set
        if not team_stats[home_team_name]['name']:
            team_stats[home_team_name]['name'] = home_team_name
        if not team_stats[away_team_name]['name']:
            team_stats[away_team_name]['name'] = away_team_name

        home_goals, away_goals = parse_score(score_str)

        if home_goals is not None and away_goals is not None: # If the score is valid
            # Update played matches
            team_stats[home_team_name]['played'] += 1
            team_stats[away_team_name]['played'] += 1

            # Update goals
            team_stats[home_team_name]['goals_for'] += home_goals
            team_stats[home_team_name]['goals_against'] += away_goals
            team_stats[away_team_name]['goals_for'] += away_goals
            team_stats[away_team_name]['goals_against'] += home_goals

            # Determine result and update W-D-L and points
            if home_goals > away_goals: # Home win
                team_stats[home_team_name]['won'] += 1
                team_stats[home_team_name]['points'] += 3
                team_stats[away_team_name]['lost'] += 1
            elif away_goals > home_goals: # Away win
                team_stats[away_team_name]['won'] += 1
                team_stats[away_team_name]['points'] += 3
                team_stats[home_team_name]['lost'] += 1
            else: # Draw
                team_stats[home_team_name]['drawn'] += 1
                team_stats[home_team_name]['points'] += 1
                team_stats[away_team_name]['drawn'] += 1
                
    # Convert defaultdict to list and calculate goal difference
    leaderboard = []
    for team_name, stats in team_stats.items():
        stats['goal_difference'] = stats['goals_for'] - stats['goals_against']
        leaderboard.append(stats)

    # Sort leaderboard: 1. Points (desc), 2. Goal Diff (desc), 3. Goals For (desc), 4. Name (asc)
    leaderboard.sort(key=lambda x: (x['points'], x['goal_difference'], x['goals_for'], x['name']), reverse=True)
    # For name, reverse=False (ascending), so we need a trick or multi-step sort.
    # Or sort by name asc first, then stable sort by others desc.
    leaderboard.sort(key=lambda x: x['name']) # Sort by name asc
    leaderboard.sort(key=lambda x: (x['points'], x['goal_difference'], x['goals_for']), reverse=True) # Stable sort by others

    return leaderboard


@app.route('/', defaults={'league_id': DEFAULT_LEAGUE_ID}, methods=['GET', 'POST'])
@app.route('/league/<league_id>/results', methods=['GET', 'POST']) # Changed route for clarity
def show_results(league_id):
    if league_id not in LEAGUES_CONFIG:
        league_id = DEFAULT_LEAGUE_ID
    
    current_league_config = LEAGUES_CONFIG[league_id]
    selected_round_url = None

    if request.method == 'POST':
        if request.form.get('league_id_form_field') == league_id:
            selected_round_url = request.form.get('round_select_url')
    else: 
        selected_round_url = request.args.get('round_url')

    url_to_scrape = selected_round_url if selected_round_url else current_league_config["results_url"]
    
    # For results page, we don't need to fetch all rounds, just the selected/current one
    page_matches, _, available_rounds, current_round_details = fetch_lmn_radgona_data(url_to_scrape, fetch_all_rounds_data=False)

    if not available_rounds and url_to_scrape != current_league_config["results_url"]:
        _, _, fallback_rounds, _ = fetch_lmn_radgona_data(current_league_config["results_url"], fetch_all_rounds_data=False)
        if fallback_rounds: available_rounds = fallback_rounds

    grouped_data = {}
    if page_matches:
        for match in page_matches:
            date_key = match['date_str']
            if date_key not in grouped_data: grouped_data[date_key] = []
            grouped_data[date_key].append(match)
    
    page_title_main = f"LMN Radgona: {current_league_config['display_name']}"
    page_title_section = current_round_details.get('name', "Rezultati")
    if page_title_section == "N/A" or "krog" not in page_title_section.lower():
        page_title_section = "Aktualni rezultati"

    return render_template('results_radgona.html', 
                           grouped_results=grouped_data,
                           all_rounds=available_rounds,
                           current_selected_url=current_round_details.get('url', url_to_scrape),
                           page_title_main=page_title_main,
                           page_title_section=page_title_section, # Changed from page_title_round
                           source_url_for_data=url_to_scrape,
                           today_date=datetime.now().date(),
                           leagues=LEAGUES_CONFIG,
                           current_league_id=league_id
                           )

@app.route('/league/<league_id>/leaderboard')
def show_leaderboard(league_id):
    if league_id not in LEAGUES_CONFIG:
        return redirect(url_for('show_leaderboard', league_id=DEFAULT_LEAGUE_ID)) # Redirect to default league leaderboard

    current_league_config = LEAGUES_CONFIG[league_id]
    
    # For leaderboard, we MUST fetch all rounds data
    # The second returned item from fetch_lmn_radgona_data is all_match_data
    print(f"Fetching all match data for {league_id} leaderboard...")
    _, all_matches_for_league, _, _ = fetch_lmn_radgona_data(current_league_config["results_url"], fetch_all_rounds_data=True)
    
    if not all_matches_for_league:
        print(f"Warning: No matches found after trying to fetch all rounds for {league_id}. Leaderboard will be empty.")
        # Optionally, render with an error message or empty board
    
    leaderboard_data = calculate_leaderboard(all_matches_for_league)
    
    page_title_main = f"LMN Radgona: {current_league_config['display_name']}"
    page_title_section = "Lestvica"

    return render_template('leaderboard.html',
                           leaderboard_data=leaderboard_data,
                           page_title_main=page_title_main,
                           page_title_section=page_title_section,
                           leagues=LEAGUES_CONFIG,
                           current_league_id=league_id,
                           source_url_for_data=current_league_config["results_url"] # Base page for this league
                           )


if __name__ == '__main__':
    # ... (extra_files logic as before)
    extra_dirs = ['templates',]
    extra_files = extra_dirs[:]
    for extra_dir in extra_dirs:
        for dirname, dirs, files in os.walk(extra_dir):
            for filename in files:
                filename = os.path.join(dirname, filename)
                if os.path.isfile(filename):
                    extra_files.append(filename)
    app.run(host="0.0.0.0", debug=True, extra_files=extra_files)