import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
from datetime import datetime
# Assuming database.py is in the same directory or accessible in PYTHONPATH
# If you want the scraper to directly call DB functions, you'd import it:
# import database

BASE_URL = "https://www.lmn-radgona.si"

def parse_slovene_date_from_header(date_str_full):
    """
    Parses a date string like 'Sobota, 03.05.2025' or 'Nedelja, 04.05.2025'
    into a datetime.date object. Returns None if parsing fails.
    """
    if not date_str_full or not isinstance(date_str_full, str):
        return None
    try:
        # Extract the DD.MM.YYYY part
        date_part_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', date_str_full)
        if date_part_match:
            date_part = date_part_match.group(1)
            return datetime.strptime(date_part, '%d.%m.%Y').date()
    except ValueError:
        # print(f"ValueError parsing date: {date_str_full}") # Optional: for debugging
        return None
    return None

def extract_round_options_and_current(soup, current_url):
    """
    Extracts round names, their URLs, and identifies the currently selected round
    from the page's dropdown.
    Returns:
        - round_options (list of dicts: {'name', 'url', 'id'})
        - selected_round_info (dict for the current/selected round: {'name', 'url', 'id'})
    """
    round_options = []
    # Initialize with current_url; name and id might be updated if found
    selected_round_info = {'name': "N/A", 'url': current_url, 'id': None} 

    select_round_element = soup.find('select', id='select-round')
    if select_round_element:
        options = select_round_element.find_all('option')
        for option in options:
            round_name = option.get_text(strip=True)
            relative_url = option.get('value')
            round_id = None # For storing the numeric ID part of the round URL

            if relative_url:
                # Attempt to extract a numeric round ID from the URL path
                # Example: /results/26-liga-a-2023-24/587/0/0/0/0 -> 587
                path_parts = relative_url.split('/')
                # Look for a numeric part, typically the 5th from the end if structure is consistent
                if len(path_parts) > 4 and path_parts[-5].isdigit(): # A bit fragile, depends on URL structure
                    round_id = path_parts[-5]
                elif len(path_parts) > 3 and path_parts[-4].isdigit(): # Fallback
                    round_id = path_parts[-4]


            if round_name and relative_url:
                full_url = urljoin(BASE_URL, relative_url)
                opt_data = {'name': round_name, 'url': full_url, 'id': round_id}
                round_options.append(opt_data)
                if option.has_attr('selected'):
                    selected_round_info = opt_data # This is the initially selected round on the page
    
    # Fallback to find selected_round_info if 'selected' attribute wasn't present but URL matches
    if selected_round_info['name'] == "N/A" and current_url:
        for r_opt in round_options:
            if r_opt['url'] == current_url:
                selected_round_info = r_opt
                break
    
    # If still N/A or doesn't look like a round name, try parsing from headings
    if selected_round_info['name'] == "N/A" or "krog" not in selected_round_info['name'].lower():
        content_heading_tds = soup.find_all('td', class_='contentheading')
        for td in content_heading_tds:
            text = td.get_text(strip=True)
            if "Rezultati kroga -" in text:
                match_re = re.search(r'Rezultati kroga - ([^()]+)', text) # Get text before parenthesis
                if match_re:
                    parsed_name = match_re.group(1).strip()
                    if "krog" in parsed_name.lower(): # Check if it's a plausible round name
                        selected_round_info['name'] = parsed_name
                break # Found a heading, assume it's the one
                
    return round_options, selected_round_info

def parse_score(score_str):
    """
    Parses a score string like '2 - 1' into (home_goals, away_goals).
    Returns (None, None) if the score is not valid or not played.
    """
    if not score_str or not isinstance(score_str, str):
        return None, None
    
    cleaned_score_str = score_str.strip().lower()
    
    if cleaned_score_str in ["n/p", "_ - _", "preloženo", "prelozeno", "odpovedano"]: # Handle variations
        return None, None
    
    # Regex to find two numbers separated by a hyphen (allowing spaces)
    match = re.fullmatch(r'(\d+)\s*-\s*(\d+)', cleaned_score_str)
    if match:
        try:
            home_goals = int(match.group(1))
            away_goals = int(match.group(2))
            return home_goals, away_goals
        except ValueError:
            # print(f"ValueError parsing score digits: {score_str}") # Optional debug
            return None, None
    
    # print(f"Could not parse score: {score_str}") # Optional debug
    return None, None


def _parse_matches_from_soup(soup_obj, round_name_for_match="N/A", round_url_source="N/A"):
    """Internal helper to parse matches from a given BeautifulSoup soup object."""
    matches_found = []
    fixtures_table = soup_obj.find('table', class_='fixtures-results')
    if not fixtures_table:
        # print(f"No 'fixtures-results' table found for round: {round_name_for_match}") # Optional debug
        return matches_found

    current_date_str_from_header = "N/A"
    for row in fixtures_table.find_all('tr', recursive=False):
        if 'sectiontableheader' in row.get('class', []):
            date_th = row.find('th')
            current_date_str_from_header = date_th.get_text(strip=True) if date_th and date_th.get_text(strip=True) else "Datum ni določen"
            continue

        if 'sectiontableentry1' in row.get('class', []) or 'sectiontableentry2' in row.get('class', []):
            cells = row.find_all('td', recursive=False)
            if len(cells) >= 10:
                try:
                    match_time_abbr = cells[1].find('abbr', class_='dtstart')
                    match_time = match_time_abbr.get_text(strip=True) if match_time_abbr else "N/A"
                    
                    home_team_span = cells[3].find('span')
                    home_team = home_team_span.get_text(strip=True) if home_team_span else "N/A"
                    
                    score_cell_link = cells[5].find('a')
                    score_span = score_cell_link.find('span', class_=re.compile(r'score.*')) if score_cell_link else None
                    score_str = "N/P" # Default
                    if score_span:
                        score_raw = score_span.get_text(separator="").replace('\xa0', ' ').strip()
                        # Check if it contains digits or "preloženo" before assigning
                        if any(char.isdigit() for char in score_raw) or "preloženo" in score_raw.lower():
                            score_str = score_raw
                        elif "_ - _" in score_raw: # Specific placeholder
                            score_str = "N/P"
                    elif score_cell_link and score_cell_link.get_text(strip=True) == "-":
                        score_str = "N/P"

                    away_team_span = cells[7].find('span')
                    away_team = away_team_span.get_text(strip=True) if away_team_span else "N/A"
                    
                    venue_cell = cells[9].find('a')
                    venue = venue_cell.get_text(strip=True) if venue_cell else "N/A"
                    
                    parsed_date_obj = parse_slovene_date_from_header(current_date_str_from_header)

                    if home_team == "N/A" or away_team == "N/A" or not home_team or not away_team:
                        # print(f"Skipping match due to missing team names: {home_team} vs {away_team}")
                        continue

                    matches_found.append({
                        'round_name': round_name_for_match,
                        'round_url': round_url_source, # URL of the page this match list was scraped from
                        'date_str': current_date_str_from_header,
                        'date_obj': parsed_date_obj,
                        'time': match_time,
                        'home_team': home_team,
                        'score_str': score_str,
                        'away_team': away_team,
                        'venue': venue
                    })
                except Exception as e_parse:
                    print(f"Error parsing a match row in round {round_name_for_match}: {e_parse} | Row: {str(row)[:100]}...")
    return matches_found


def fetch_lmn_radgona_data(url_to_scrape, fetch_all_rounds_data=False, league_id_for_caching=None): # Added league_id_for_caching
    page_matches = []
    all_match_data_for_leaderboard = [] if fetch_all_rounds_data else None # Initialize correctly
    available_rounds = []
    current_round_info = {'name': "N/A", 'url': url_to_scrape, 'id': None}
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        print(f"Fetching initial page: {url_to_scrape}")
        response = requests.get(url_to_scrape, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        available_rounds, current_round_info_from_page = extract_round_options_and_current(soup, url_to_scrape)
        if current_round_info_from_page['name'] != "N/A":
            current_round_info = current_round_info_from_page

        # Parse matches for the current page (the one specified by url_to_scrape)
        # This is important to get current_round_info correct even if not fetching all rounds.
        page_matches = _parse_matches_from_soup(soup, current_round_info['name'], current_round_info['url'])
        print(f"Found {len(page_matches)} matches on initial page '{current_round_info['name']}' ({current_round_info['url']})")

        if fetch_all_rounds_data:
            all_match_data_for_leaderboard = [] # Re-initialize for clarity
            print(f"Fetching ALL rounds data. Total rounds from dropdown: {len(available_rounds)}")
            unique_match_identifiers = set()

            # If available_rounds is empty from initial page, something is wrong, don't proceed with all rounds.
            if not available_rounds:
                print("WARNING: No available_rounds found on initial page. Cannot fetch all rounds data.")
                # Use only page_matches if any, for the leaderboard in this case.
                all_match_data_for_leaderboard.extend(page_matches) # Add what we have
            else:
                for i, round_opt in enumerate(available_rounds):
                    round_url_to_fetch = round_opt['url']
                    round_name_to_use = round_opt['name']
                    
                    matches_for_this_specific_round = []

                    # If the current round_opt is the same as the initially scraped page, use page_matches
                    if round_url_to_fetch == url_to_scrape:
                        matches_for_this_specific_round = page_matches
                        print(f"  ({i+1}/{len(available_rounds)}) Using pre-fetched matches for: {round_name_to_use}")
                    else:
                        try:
                            print(f"  ({i+1}/{len(available_rounds)}) Fetching round: {round_name_to_use} from {round_url_to_fetch}")
                            round_response = requests.get(round_url_to_fetch, headers=headers, timeout=10)
                            round_response.raise_for_status()
                            round_soup = BeautifulSoup(round_response.content, 'html.parser')
                            matches_for_this_specific_round = _parse_matches_from_soup(round_soup, round_name_to_use, round_url_to_fetch)
                            print(f"    Found {len(matches_for_this_specific_round)} matches for round {round_name_to_use}")
                        except requests.exceptions.RequestException as e_round:
                            print(f"    Error fetching round {round_name_to_use} URL {round_url_to_fetch}: {e_round}")
                        except Exception as e_all_rounds_inner:
                            print(f"    An unexpected error for round {round_name_to_use}: {e_all_rounds_inner}")
                            import traceback
                            traceback.print_exc()
                    
                    # Add unique matches from this round to the overall list
                    for match_item in matches_for_this_specific_round:
                        # Create a more robust identifier if round IDs are reliable
                        round_id_for_key = round_opt.get('id', match_item.get('round_name', 'N/A')) 
                        match_id_key = (match_item['home_team'], match_item['away_team'], round_id_for_key, match_item.get('date_str', 'N/A'))
                        
                        if match_id_key not in unique_match_identifiers:
                            all_match_data_for_leaderboard.append(match_item)
                            unique_match_identifiers.add(match_id_key)
            
            print(f"Finished fetching all rounds. Total unique matches collected for leaderboard: {len(all_match_data_for_leaderboard)}")
            
    except requests.exceptions.RequestException as e_main:
        print(f"Main error fetching URL {url_to_scrape}: {e_main}")
    except Exception as e_fatal:
        print(f"A fatal error occurred during initial scrape of {url_to_scrape}: {e_fatal}")
        import traceback
        traceback.print_exc()
            
    return page_matches, all_match_data_for_leaderboard, available_rounds, current_round_info


if __name__ == '__main__':
    # Test fetching only a specific round's page
    print("--- TESTING SINGLE ROUND FETCH ---")
    # test_round_21_url_A = "https://www.lmn-radgona.si/index.php/ct-menu-item-7/razpored-liga-a/results/26-liga-a-2023-24/587/0/0/0/0"
    # page_m, _, avail_r, curr_r_info = fetch_lmn_radgona_data(test_round_21_url_A, fetch_all_rounds_data=False)
    # print(f"Page Matches ({curr_r_info['name']}): {len(page_m)}")
    # for m in page_m[:2]: print(m)
    # print(f"Available Rounds on page: {len(avail_r)}")

    print("\n--- TESTING FETCH ALL ROUNDS FOR LEADERBOARD (LIGA A) ---")
    liga_a_main_results_url = "https://www.lmn-radgona.si/index.php/ct-menu-item-7/razpored-liga-a"
    _, all_matches_data, all_rounds_list, current_round = fetch_lmn_radgona_data(liga_a_main_results_url, fetch_all_rounds_data=True)

    if all_matches_data:
        print(f"\nTotal unique matches scraped for Liga A leaderboard: {len(all_matches_data)}")
        # for m_idx, m in enumerate(all_matches_data):
        #     if m_idx < 2 or m_idx > len(all_matches_data) - 3:
        #         print(f"  {m['round_name']} ({m['round_url'].split('/')[-5]}): {m['date_str']} - {m['home_team']} {m['score_str']} {m['away_team']}")
        #     elif m_idx == 2:
        #         print("  ...")
        
        # Test score parsing on collected data
        print("\nTesting score parsing on some collected matches:")
        parsed_count = 0
        for m in all_matches_data:
            if parsed_count < 5 and m['score_str'] != "N/P":
                hg, ag = parse_score(m['score_str'])
                print(f"Original: '{m['score_str']}' -> Parsed: ({hg}, {ag})")
                if hg is not None: parsed_count +=1
            elif m['score_str'] == "N/P" and parsed_count < 5:
                 hg, ag = parse_score(m['score_str'])
                 print(f"Original: '{m['score_str']}' -> Parsed: ({hg}, {ag})")


    else:
        print("No matches collected for leaderboard calculation for Liga A.")

    print(f"\nAvailable rounds found on Liga A main page: {len(all_rounds_list)}")
    print(f"Current round info from Liga A main page: {current_round}")

    # print("\n--- TESTING FETCH ALL ROUNDS FOR LEADERBOARD (LIGA B) ---")
    # liga_b_main_results_url = "https://www.lmn-radgona.si/index.php/2017-08-11-13-54-06/razpored-liga-b"
    # _, all_matches_data_b, _, _ = fetch_lmn_radgona_data(liga_b_main_results_url, fetch_all_rounds_data=True)
    # if all_matches_data_b:
    #     print(f"\nTotal unique matches scraped for Liga B leaderboard: {len(all_matches_data_b)}")