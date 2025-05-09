from flask import Flask, render_template, request, redirect, url_for
from scraper_radgona import fetch_lmn_radgona_data, BASE_URL
import os
from datetime import datetime
from urllib.parse import urljoin # <<< --- ADD THIS IMPORT

app = Flask(__name__)

# This URL on the target site usually shows the current/next round and has the full selector
INITIAL_LOAD_URL = urljoin(BASE_URL, "/index.php/ct-menu-item-7/razpored-liga-a")

@app.route('/', methods=['GET', 'POST'])
def show_results():
    selected_round_url = None
    # source_for_rounds_list = INITIAL_LOAD_URL # Not strictly needed here anymore

    if request.method == 'POST':
        selected_round_url = request.form.get('round_select_url')
    else: # GET request
        selected_round_url = request.args.get('round_url')

    if not selected_round_url:
        # This is the initial load or no specific round was requested
        print("Initial load or no round specified, using INITIAL_LOAD_URL.")
        url_to_scrape = INITIAL_LOAD_URL
    else:
        url_to_scrape = selected_round_url

    matches, all_rounds, current_round_details = fetch_lmn_radgona_data(url_to_scrape)

    # If `all_rounds` is empty (e.g., direct link to a page without the selector),
    # try fetching them from the `INITIAL_LOAD_URL`.
    # This can happen if a user bookmarks a direct round URL that might not have the full selector in its own HTML.
    if not all_rounds and url_to_scrape != INITIAL_LOAD_URL:
        print(f"No rounds found on {url_to_scrape}, trying to get rounds list from {INITIAL_LOAD_URL}")
        _, fallback_rounds, _ = fetch_lmn_radgona_data(INITIAL_LOAD_URL)
        if fallback_rounds:
            all_rounds = fallback_rounds
            print(f"Successfully fetched fallback rounds list ({len(all_rounds)} rounds).")
        else:
            print(f"Failed to fetch fallback rounds from {INITIAL_LOAD_URL}.")


    grouped_data = {}
    if matches:
        for match in matches:
            date_key = match['date_str'] # Use the original string date for grouping display
            if date_key not in grouped_data:
                grouped_data[date_key] = []
            grouped_data[date_key].append(match)
    
    page_title_main = "LMN Radgona"
    page_title_round = current_round_details.get('name', "Rezultati")
    if page_title_round == "N/A" or "krog" not in page_title_round.lower(): # Check if it actually looks like a round name
        page_title_round = "Aktualni rezultati"


    return render_template('results_radgona.html', 
                           grouped_results=grouped_data,
                           all_rounds=all_rounds,
                           current_selected_url=current_round_details.get('url', url_to_scrape),
                           page_title_main=page_title_main,
                           page_title_round=page_title_round,
                           source_url_for_data=url_to_scrape, # The URL actual data came from
                           today_date=datetime.now().date() 
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
    app.run(host='0.0.0.0', port=5000, debug=True)