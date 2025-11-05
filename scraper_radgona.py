import requests
from bs4 import BeautifulSoup
import re
import os
import time
import random
from urllib.parse import urljoin
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://www.lmn-radgona.si"

def parse_slovene_date_from_header(date_str_full):
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
                path_parts = relative_url.split('/')
                if len(path_parts) > 4 and path_parts[-5].isdigit():
                    round_id = path_parts[-5]
                elif len(path_parts) > 3 and path_parts[-4].isdigit():
                    round_id = path_parts[-4]
            if round_name and relative_url:
                full_url = urljoin(BASE_URL, relative_url)
                opt_data = {'name': round_name, 'url': full_url, 'id': round_id}
                round_options.append(opt_data)
                if option.has_attr('selected'):
                    selected_round_info = opt_data
    if selected_round_info['name'] == "N/A" and current_url:
        for r_opt in round_options:
            if r_opt['url'] == current_url:
                selected_round_info = r_opt
                break
    if selected_round_info['name'] == "N/A" or "krog" not in selected_round_info['name'].lower():
        content_heading_tds = soup.find_all('td', class_='contentheading')
        for td in content_heading_tds:
            text = td.get_text(strip=True)
            if "Rezultati kroga -" in text:
                match_re = re.search(r'Rezultati kroga - ([^()]+)', text)
                if match_re:
                    parsed_name = match_re.group(1).strip()
                    if "krog" in parsed_name.lower():
                        selected_round_info['name'] = parsed_name
                break
    return round_options, selected_round_info

def parse_score(score_str):
    if not score_str or not isinstance(score_str, str):
        return None, None
    cleaned_score_str = score_str.strip().lower()
    if cleaned_score_str in ["n/p", "_ - _", "preloženo", "prelozeno", "odpovedano"]:
        return None, None
    match = re.fullmatch(r'(\d+)\s*-\s*(\d+)', cleaned_score_str)
    if match:
        try:
            home_goals = int(match.group(1))
            away_goals = int(match.group(2))
            return home_goals, away_goals
        except ValueError:
            return None, None
    return None, None

def _parse_matches_from_soup(soup_obj, round_name_for_match="N/A", round_url_source="N/A"):
    debug_mode = os.environ.get('SCRAPER_DEBUG', 'false').lower() == 'true'
    
    matches_found = []
    fixtures_table = soup_obj.find('table', class_='fixtures-results')
    if not fixtures_table:
        print(f"[ERROR] No fixtures-results table found")
        if debug_mode:
            # Let's see what tables are available
            all_tables = soup_obj.find_all('table')
            print(f"[DEBUG] Found {len(all_tables)} tables total")
            for i, table in enumerate(all_tables[:5]):  # Show first 5 tables
                classes = table.get('class', [])
                print(f"[DEBUG] Table {i}: classes={classes}")
        return matches_found
    
    if debug_mode:
        print(f"[DEBUG] Found fixtures-results table")

    current_date_str_from_header = "N/A"
    rows_found = fixtures_table.find_all('tr', recursive=False)
    if debug_mode:
        print(f"[DEBUG] Found {len(rows_found)} rows in fixtures table")
    
    for row_idx, row in enumerate(rows_found):
        row_classes = row.get('class', [])
        if 'sectiontableheader' in row_classes:
            date_th = row.find('th')
            current_date_str_from_header = date_th.get_text(strip=True) if date_th and date_th.get_text(strip=True) else "Datum ni določen"
            if debug_mode:
                print(f"[DEBUG] Row {row_idx}: Date header = '{current_date_str_from_header}'")
            continue

        if 'sectiontableentry1' in row_classes or 'sectiontableentry2' in row_classes:
            cells = row.find_all('td', recursive=False)
            if debug_mode:
                print(f"[DEBUG] Row {row_idx}: Match row with {len(cells)} cells")
            if len(cells) >= 10:
                try:
                    # Nova verzija – pobere <span> iz .time-container
                    # Try original method first
                    match_time = "N/A"
                    match_time_container = cells[1].find('div', class_='time-container')
                    match_time_span = match_time_container.find('span') if match_time_container else None
                    if match_time_span:
                        match_time = match_time_span.get_text(strip=True)
                    else:
                        # Try BeautifulSoup fallback for abbr tag
                        try:
                            abbr_tag = cells[1].find('abbr')
                            if abbr_tag:
                                match_time = abbr_tag.get_text(strip=True)
                            else:
                                # Poskusimo najti v vseh elementih časovnega stolpca
                                all_text = cells[1].get_text(strip=True)
                                # Preverimo za standardne formate ure (HH:MM)
                                time_match = re.search(r'\b(\d{1,2}:\d{2})\b', all_text)
                                if time_match:
                                    match_time = time_match.group(1)
                        except Exception as e_fallback:
                            print(f"[BeautifulSoup fallback error] Could not extract time: {e_fallback}")


                    home_team_span = cells[3].find('span')
                    home_team = home_team_span.get_text(strip=True) if home_team_span else "N/A"
                    score_cell_link = cells[5].find('a')
                    score_span = score_cell_link.find('span', class_=re.compile(r'score.*')) if score_cell_link else None
                    score_str = "N/P"
                    if score_span:
                        score_raw = score_span.get_text(separator="").replace('\xa0', ' ').strip()
                        if any(char.isdigit() for char in score_raw) or "preloženo" in score_raw.lower():
                            score_str = score_raw
                        elif "_ - _" in score_raw:
                            score_str = "N/P"
                    elif score_cell_link and score_cell_link.get_text(strip=True) == "-":
                        score_str = "N/P"
                    away_team_span = cells[7].find('span')
                    away_team = away_team_span.get_text(strip=True) if away_team_span else "N/A"
                    venue_cell = cells[9].find('a')
                    venue = venue_cell.get_text(strip=True) if venue_cell else "N/A"
                    parsed_date_obj = parse_slovene_date_from_header(current_date_str_from_header)
                    if home_team == "N/A" or away_team == "N/A" or not home_team or not away_team:
                        continue
                    matches_found.append({
                        'round_name': round_name_for_match,
                        'round_url': round_url_source,
                        'date_str': current_date_str_from_header,
                        'date_obj': parsed_date_obj,
                        'time': match_time,
                        'home_team': home_team,
                        'score_str': score_str,
                        'away_team': away_team,
                        'venue': venue
                    })
                except Exception as e_parse:
                    print(f"Error parsing match row: {e_parse}")
    return matches_found

def fetch_lmn_radgona_data(url_to_scrape, fetch_all_rounds_data=False, league_id_for_caching=None):
    debug_mode = os.environ.get('SCRAPER_DEBUG', 'false').lower() == 'true'
    
    if debug_mode:
        print(f"[DEBUG] Starting scrape for: {url_to_scrape}")
        print(f"[DEBUG] Fetch all rounds: {fetch_all_rounds_data}")
    
    page_matches = []
    all_match_data_for_leaderboard = [] if fetch_all_rounds_data else None
    available_rounds = []
    current_round_info = {'name': "N/A", 'url': url_to_scrape, 'id': None}
    
    # Advanced headers to bypass Cloudflare bot detection
    # Include security headers that real browsers send
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'sl-SI,sl;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0'
    }
    session = requests.Session()
    session.headers.update(headers)
    
    try:
        # First establish session by visiting homepage (helps bypass bot detection)
        try:
            homepage_response = session.get(BASE_URL, timeout=20)
            if debug_mode:
                print(f"[DEBUG] Homepage visit status: {homepage_response.status_code}")
            
            # Check for Cloudflare challenge on homepage
            if "One moment, please" in homepage_response.text:
                if debug_mode:
                    print(f"[DEBUG] Cloudflare challenge detected on homepage")
                raise Exception("Cloudflare bot detection active")
                
            # Wait like a human would before navigating
            time.sleep(random.uniform(1, 2))
            
        except Exception as e:
            if debug_mode:
                print(f"[DEBUG] Homepage visit failed: {e}")
            # Continue anyway, but log the issue
        
        # Update headers for same-origin navigation
        session.headers.update({
            'Referer': BASE_URL,
            'Sec-Fetch-Site': 'same-origin'
        })
        
        # Dodamo retry mehanizem z različnimi headerji
        for attempt in range(3):
            try:
                if attempt == 1:
                    # Drugi poskus z drugačnim User-Agent
                    session.headers.update({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0'
                    })
                elif attempt == 2:
                    # Tretji poskus z osnovnim User-Agent
                    session.headers.update({
                        'User-Agent': 'Mozilla/5.0 (compatible; MSIE 10.0; Windows NT 6.1; WOW64; Trident/6.0)'
                    })
                
                # Dodamo kratko zakavo za izogibanje rate limitom
                if attempt > 0:
                    time.sleep(random.uniform(1, 3))
                
                response = session.get(url_to_scrape, timeout=20, allow_redirects=True)
                
                # Check for Cloudflare challenge
                if "One moment, please" in response.text:
                    if debug_mode:
                        print(f"[DEBUG] Cloudflare challenge detected on attempt {attempt + 1}")
                    if attempt == 2:
                        raise Exception("Cloudflare bot detection preventing access")
                    continue
                
                # Preverimo če smo dobili pravilno stran
                if response.status_code == 200:
                    content_type = response.headers.get('content-type', '').lower()
                    if debug_mode:
                        print(f"[DEBUG] Response status: {response.status_code}, content-type: {content_type}, length: {len(response.content)}")
                    if 'text/html' in content_type:
                        soup = BeautifulSoup(response.content, 'html.parser')
                        if debug_mode:
                            print(f"[DEBUG] Successfully parsed HTML, title: {soup.title.string if soup.title else 'No title'}")
                            # Check for tables immediately to debug the issue
                            fixtures_table = soup.find('table', class_='fixtures-results')
                            all_tables = soup.find_all('table')
                            print(f"[DEBUG] Tables found: {len(all_tables)} total, fixtures-results: {fixtures_table is not None}")
                            if len(all_tables) == 0:
                                # If no tables, show some content for debugging
                                body_text = soup.get_text()[:500]
                                print(f"[DEBUG] No tables found! First 500 chars: {body_text}")
                        break
                    else:
                        print(f"[ERROR] Unexpected content type: {content_type}")
                        if attempt == 2:
                            raise Exception(f"Invalid content type: {content_type}")
                        continue
                else:
                    print(f"[ERROR] HTTP {response.status_code}: {response.reason}")
                    response.raise_for_status()
                    
            except requests.exceptions.RequestException as e:
                print(f"Request attempt {attempt + 1} failed: {e}")
                if attempt == 2:
                    raise
                continue
        else:
            raise Exception("All retry attempts failed")
        available_rounds, current_round_info_from_page = extract_round_options_and_current(soup, url_to_scrape)
        if debug_mode:
            print(f"[DEBUG] Found {len(available_rounds)} rounds")
        if current_round_info_from_page['name'] != "N/A":
            current_round_info = current_round_info_from_page
        if debug_mode:
            print(f"[DEBUG] Current round info: {current_round_info}")
        page_matches = _parse_matches_from_soup(soup, current_round_info['name'], current_round_info['url'])
        if debug_mode:
            print(f"[DEBUG] Parsed {len(page_matches)} matches from main page")

        if fetch_all_rounds_data and available_rounds:
            all_match_data_for_leaderboard = []
            unique_match_identifiers = set()
            # Zmanjšajmo število vzporednih zahtev za izogibanje rate limitom
            max_workers = int(os.environ.get("SCRAPER_MAX_WORKERS", 3))

            def fetch_round(round_opt):
                try:
                    if round_opt['url'] == url_to_scrape:
                        return page_matches
                    
                    # Uporabimo isto retry logiko
                    for attempt in range(2):
                        try:
                            # Kratka zakava med zahtevki
                            if attempt > 0:
                                time.sleep(random.uniform(0.5, 2))
                            
                            r = session.get(round_opt['url'], timeout=10, allow_redirects=True)
                            if r.status_code == 200:
                                content_type = r.headers.get('content-type', '').lower()
                                if 'text/html' in content_type:
                                    s = BeautifulSoup(r.content, 'html.parser')
                                    return _parse_matches_from_soup(s, round_opt['name'], round_opt['url'])
                            r.raise_for_status()
                        except requests.exceptions.RequestException as e:
                            print(f"Attempt {attempt + 1} failed for {round_opt['name']}: {e}")
                            if attempt == 1:
                                raise
                            continue
                    return []
                except Exception as e:
                    print(f"Error fetching {round_opt['name']}: {e}")
                    return []

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_round = {executor.submit(fetch_round, round_opt): round_opt for round_opt in available_rounds}
                for future in as_completed(future_to_round):
                    matches = future.result()
                    for match_item in matches:
                        round_id_for_key = match_item.get('round_name', 'N/A')
                        match_id_key = (
                            match_item['home_team'], match_item['away_team'], round_id_for_key, match_item.get('date_str', 'N/A'))
                        if match_id_key not in unique_match_identifiers:
                            all_match_data_for_leaderboard.append(match_item)
                            unique_match_identifiers.add(match_id_key)
            # Always include matches from main page, deduped
            for match_item in page_matches:
                round_id_for_key = match_item.get('round_name', 'N/A')
                match_id_key = (
                    match_item['home_team'], match_item['away_team'], round_id_for_key, match_item.get('date_str', 'N/A'))
                if match_id_key not in unique_match_identifiers:
                    all_match_data_for_leaderboard.append(match_item)
                    unique_match_identifiers.add(match_id_key)
    except Exception as e_fatal:
        print(f"Fatal error during scrape: {e_fatal}")
        import traceback
        traceback.print_exc()

    if debug_mode:
        print(f"[DEBUG] Returning: {len(page_matches)} page matches, {len(all_match_data_for_leaderboard) if all_match_data_for_leaderboard else 'None'} all matches")
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
    # else:
    #     print("No matches collected for Liga B")