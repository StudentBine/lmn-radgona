# scraper_radgona.py (relevant parts, assume others are as before)
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse, parse_qs
from datetime import datetime

BASE_URL = "https://www.lmn-radgona.si"

def parse_slovene_date_from_header(date_str_full):
    # ... (as before)
    if not date_str_full or not isinstance(date_str_full, str):
        return None
    try:
        date_part_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', date_str_full)
        if date_part_match:
            date_part = date_part_match.group(1)
            return datetime.strptime(date_part, '%d.%m.%Y').date()
    except ValueError:
        return None
    return None

def extract_round_options_and_current(soup, current_url):
    # ... (as before)
    round_options = []
    selected_round_info = {'name': "N/A", 'url': current_url, 'id': None}

    select_round_element = soup.find('select', id='select-round')
    if select_round_element:
        options = select_round_element.find_all('option')
        for option in options:
            round_name = option.get_text(strip=True)
            relative_url = option.get('value')
            round_id = None
            if relative_url:
                # Try to extract round ID from URL, e.g., /587/ in the path
                path_parts = relative_url.split('/')
                for part in reversed(path_parts): # Search from end
                    if part.isdigit() and len(path_parts) > 5: # Basic check
                        round_id = part
                        break
            
            if round_name and relative_url:
                full_url = urljoin(BASE_URL, relative_url)
                opt_data = {'name': round_name, 'url': full_url, 'id': round_id}
                round_options.append(opt_data)
                if option.has_attr('selected'):
                    selected_round_info = opt_data
    
    if selected_round_info['name'] == "N/A": # Fallback if 'selected' not present
        for r_opt in round_options:
            if r_opt['url'] == current_url:
                selected_round_info = r_opt
                break
    
    if selected_round_info['name'] == "N/A" or "krog" not in selected_round_info['name']:
        content_heading_tds = soup.find_all('td', class_='contentheading')
        for td in content_heading_tds:
            text = td.get_text(strip=True)
            if "Rezultati kroga -" in text:
                match = re.search(r'Rezultati kroga - (\d+\. krog)', text)
                if match:
                    selected_round_info['name'] = match.group(1)
                else:
                    parsed_heading_round = text.replace("Rezultati kroga -", "").split('(')[0].strip()
                    if "krog" in parsed_heading_round:
                         selected_round_info['name'] = parsed_heading_round
                break
                
    return round_options, selected_round_info


def parse_score(score_str):
    """
    Parses a score string like '2 - 1' into (home_goals, away_goals).
    Returns (None, None) if the score is not valid or not played.
    """
    if not score_str or score_str.strip().lower() in ["n/p", "_ - _", "preloženo"]:
        return None, None
    
    score_parts = score_str.split('-')
    if len(score_parts) == 2:
        try:
            home_goals = int(score_parts[0].strip())
            away_goals = int(score_parts[1].strip())
            return home_goals, away_goals
        except ValueError:
            return None, None # Could not convert to int
    return None, None


def fetch_lmn_radgona_data(url_to_scrape, fetch_all_rounds_data=False):
    """
    Fetches match results from the given URL.
    If fetch_all_rounds_data is True, it will try to scrape all rounds for leaderboard calculation.
    Returns:
        - matches for the current page/round
        - all_match_data (if fetch_all_rounds_data is True, else None)
        - available_rounds (list of dicts for dropdown)
        - current_round_info (dict for the current page/round)
    """
    page_matches = []
    all_match_data_for_leaderboard = [] if fetch_all_rounds_data else None
    available_rounds = []
    current_round_info = {'name': "N/A", 'url': url_to_scrape, 'id': None}
    
    # --- Initial fetch to get round options and current page data ---
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        print(f"Fetching data from: {url_to_scrape}")
        response = requests.get(url_to_scrape, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        available_rounds, current_round_info_from_select = extract_round_options_and_current(soup, url_to_scrape)
        if current_round_info_from_select['name'] != "N/A": # Update if select box provided better name/id
            current_round_info = current_round_info_from_select

        # --- Function to parse matches from a soup object ---
        def _parse_matches_from_soup(soup_obj, round_name_for_match="N/A"):
            matches_found = []
            fixtures_table = soup_obj.find('table', class_='fixtures-results')
            if not fixtures_table: return matches_found

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
                            score_str = "N/P"
                            if score_span:
                                score_raw = score_span.get_text(separator="").replace('\xa0', ' ').strip()
                                if any(char.isdigit() for char in score_raw) or "preloženo" in score_raw.lower():
                                    score_str = score_raw
                                elif "_ - _" in score_raw: score_str = "N/P"
                            elif score_cell_link and score_cell_link.get_text(strip=True) == "-": score_str = "N/P"

                            away_team_span = cells[7].find('span')
                            away_team = away_team_span.get_text(strip=True) if away_team_span else "N/A"
                            venue_cell = cells[9].find('a')
                            venue = venue_cell.get_text(strip=True) if venue_cell else "N/A"
                            parsed_date_obj = parse_slovene_date_from_header(current_date_str_from_header)

                            # Skip if essential team names are missing
                            if home_team == "N/A" or away_team == "N/A": continue

                            matches_found.append({
                                'round_name': round_name_for_match, # Store which round this match belongs to
                                'date_str': current_date_str_from_header,
                                'date_obj': parsed_date_obj,
                                'time': match_time,
                                'home_team': home_team,
                                'score_str': score_str, # Store the raw score string
                                'away_team': away_team,
                                'venue': venue
                            })
                        except Exception as e_parse:
                            print(f"Error parsing match row: {e_parse}")
            return matches_found

        # Parse matches for the current page
        page_matches = _parse_matches_from_soup(soup, current_round_info['name'])

        # --- If fetch_all_rounds_data is True, iterate and scrape all rounds ---
        if fetch_all_rounds_data and available_rounds:
            print(f"Fetching all rounds data for leaderboard. Total rounds: {len(available_rounds)}")
            # Use a set to avoid duplicate matches if a match appears in multiple rounds (unlikely but possible)
            unique_match_identifiers = set()

            for i, round_opt in enumerate(available_rounds):
                # Don't re-scrape the current page if its data is already parsed
                # if round_opt['url'] == url_to_scrape and page_matches:
                #     for match in page_matches:
                #         match_id = f"{match['home_team']}-{match['away_team']}-{match.get('date_str','N/A')}-{match.get('score_str','N/P')}"
                #         if match_id not in unique_match_identifiers:
                #             all_match_data_for_leaderboard.append(match)
                #             unique_match_identifiers.add(match_id)
                #     print(f"({i+1}/{len(available_rounds)}) Used current page data for round: {round_opt['name']}")
                #     continue
                
                # Check if this round has already been processed by its ID (if round_id is reliable)
                # This is an optimization; for simplicity, we can re-parse all.
                # However, the current_round_info might be from a default page, not a specific round url.
                # So, it's safer to just fetch all if fetch_all_rounds_data is True.
                
                try:
                    print(f"({i+1}/{len(available_rounds)}) Fetching round: {round_opt['name']} from {round_opt['url']}")
                    round_response = requests.get(round_opt['url'], headers=headers, timeout=10)
                    round_response.raise_for_status()
                    round_soup = BeautifulSoup(round_response.content, 'html.parser')
                    matches_from_round = _parse_matches_from_soup(round_soup, round_opt['name'])
                    
                    for match in matches_from_round:
                        # Create a more robust identifier for a match
                        match_id = f"{match['home_team']}-{match['away_team']}-{match.get('date_str','N/A')}-{match.get('round_name', 'N/A')}"
                        # Alternative: identify by teams and round ID if available and unique
                        # if round_opt.get('id'):
                        #    match_id = f"{match['home_team']}-{match['away_team']}-{round_opt['id']}"
                        
                        if match_id not in unique_match_identifiers:
                            all_match_data_for_leaderboard.append(match)
                            unique_match_identifiers.add(match_id)
                        # else:
                        #     print(f"  Skipping duplicate match: {match_id}")


                except requests.exceptions.RequestException as e_round:
                    print(f"  Error fetching round {round_opt['name']}: {e_round}")
                except Exception as e_all:
                    print(f"  An unexpected error occurred for round {round_opt['name']}: {e_all}")
                    import traceback
                    traceback.print_exc()
            print(f"Finished fetching all rounds. Total unique matches for leaderboard: {len(all_match_data_for_leaderboard)}")
            
    except requests.exceptions.RequestException as e_main:
        print(f"Main error fetching URL {url_to_scrape}: {e_main}")
    except Exception as e_fatal:
        print(f"A fatal error occurred during initial scrape of {url_to_scrape}: {e_fatal}")
        import traceback
        traceback.print_exc()
            
    return page_matches, all_match_data_for_leaderboard, available_rounds, current_round_info

# ... (if __name__ == '__main__' block for testing)
if __name__ == '__main__':
    # Test fetching all rounds for leaderboard
    liga_a_razpored_url = "https://www.lmn-radgona.si/index.php/ct-menu-item-7/razpored-liga-a"
    
    print("\n--- TESTING LEADERBOARD DATA FETCH ---")
    _, all_matches, rounds_list, current_r_info = fetch_lmn_radgona_data(liga_a_razpored_url, fetch_all_rounds_data=True)

    if all_matches:
        print(f"\nTotal unique matches scraped for leaderboard: {len(all_matches)}")
        # Print first few and last few matches
        for m_idx, m in enumerate(all_matches):
            if m_idx < 2 or m_idx > len(all_matches) - 3:
                print(f"  {m['round_name']}: {m['date_str']} - {m['home_team']} {m['score_str']} {m['away_team']}")
            elif m_idx == 2:
                print("  ...")
    else:
        print("No matches collected for leaderboard calculation.")

    print(f"\nAvailable rounds found: {len(rounds_list)}")
    print(f"Current round info from page: {current_r_info}")