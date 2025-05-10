from flask import Flask, render_template, request, redirect, url_for
from scraper_radgona import fetch_lmn_radgona_data, BASE_URL # BASE_URL from scraper
import os
from datetime import datetime
from urllib.parse import urljoin

app = Flask(__name__)

# --- LEAGUE CONFIGURATIONS ---
LEAGUES_CONFIG = {
    "liga_a": {
        "name": "Liga A",
        "display_name": "Liga -A-", # For display in titles
        "initial_url": urljoin(BASE_URL, "/index.php/ct-menu-item-7/razpored-liga-a")
    },
    "liga_b": {
        "name": "Liga B",
        "display_name": "Liga -B-",
        "initial_url": urljoin(BASE_URL, "/index.php/2017-08-11-13-54-06/razpored-liga-b")
    }
}
DEFAULT_LEAGUE_ID = "liga_a"

@app.route('/', defaults={'league_id': DEFAULT_LEAGUE_ID}, methods=['GET', 'POST'])
@app.route('/league/<league_id>', methods=['GET', 'POST'])
def show_results(league_id):
    if league_id not in LEAGUES_CONFIG:
        league_id = DEFAULT_LEAGUE_ID # Fallback to default if invalid league_id
    
    current_league_config = LEAGUES_CONFIG[league_id]
    
    selected_round_url = None

    if request.method == 'POST':
        # Ensure the post is for the current league to avoid mix-ups if user rapidly clicks
        if request.form.get('league_id_form_field') == league_id:
            selected_round_url = request.form.get('round_select_url')
    else: # GET request
        selected_round_url = request.args.get('round_url')

    if not selected_round_url:
        url_to_scrape = current_league_config["initial_url"]
        print(f"Initial load or no round specified for {league_id}, using its initial_url: {url_to_scrape}")
    else:
        url_to_scrape = selected_round_url
        print(f"Fetching specified round URL for {league_id}: {url_to_scrape}")

    matches, all_rounds, current_round_details = fetch_lmn_radgona_data(url_to_scrape)

    # If `all_rounds` is empty, try fetching them from the current league's `initial_url`.
    if not all_rounds and url_to_scrape != current_league_config["initial_url"]:
        print(f"No rounds found on {url_to_scrape}, trying from {current_league_config['initial_url']}")
        _, fallback_rounds, _ = fetch_lmn_radgona_data(current_league_config["initial_url"])
        if fallback_rounds:
            all_rounds = fallback_rounds
        else:
             print(f"Failed to fetch fallback rounds from {current_league_config['initial_url']}.")


    grouped_data = {}
    if matches:
        for match in matches:
            date_key = match['date_str']
            if date_key not in grouped_data:
                grouped_data[date_key] = []
            grouped_data[date_key].append(match)
    
    page_title_main = f"LMN Radgona: {current_league_config['display_name']}"
    page_title_round = current_round_details.get('name', "Rezultati")
    if page_title_round == "N/A" or "krog" not in page_title_round.lower():
        page_title_round = "Aktualni rezultati"

    return render_template('results_radgona.html', 
                           grouped_results=grouped_data,
                           all_rounds=all_rounds,
                           current_selected_url=current_round_details.get('url', url_to_scrape),
                           page_title_main=page_title_main,
                           page_title_round=page_title_round,
                           source_url_for_data=url_to_scrape,
                           today_date=datetime.now().date(),
                           leagues=LEAGUES_CONFIG, # Pass all league configs
                           current_league_id=league_id # Pass current league_id
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
    app.run(host="0.0.0.0",debug=True, extra_files=extra_files)