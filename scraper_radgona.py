import requests
from bs4 import BeautifulSoup
import re
import os
import time
import random
from urllib.parse import urljoin
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import schedule
import threading

# Import database functions for saving scraped data
try:
    from database import cache_matches, init_db, init_db_pool
    DATABASE_AVAILABLE = True
except ImportError:
    print("[WARNING] database.py not found - running without database support")
    DATABASE_AVAILABLE = False

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

def get_rotating_user_agents():
    """Return rotating user agents for different browsers including mobile"""
    return [
        # Desktop browsers
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        # Mobile browsers (often less scrutinized)
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (Android 13; Mobile; rv:120.0) Gecko/120.0 Firefox/120.0',
        'Mozilla/5.0 (Linux; Android 13; SM-S901B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
        # Older browsers
        'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:109.0) Gecko/20100101 Firefox/115.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
    ]

def fetch_lmn_radgona_data(url_to_scrape, fetch_all_rounds_data=False, league_id_for_caching=None):
    debug_mode = os.environ.get('SCRAPER_DEBUG', 'false').lower() == 'true'
    
    if debug_mode:
        print(f"[DEBUG] Starting scrape for: {url_to_scrape}")
        print(f"[DEBUG] Fetch all rounds: {fetch_all_rounds_data}")
    
    page_matches = []
    all_match_data_for_leaderboard = [] if fetch_all_rounds_data else None
    available_rounds = []
    current_round_info = {'name': "N/A", 'url': url_to_scrape, 'id': None}
    
    # Rotate through different user agents to avoid detection
    user_agents = get_rotating_user_agents()
    selected_ua = random.choice(user_agents)
    
    if debug_mode:
        print(f"[DEBUG] Using User-Agent: {selected_ua.split('/')[-1].split()[0] if '/' in selected_ua else selected_ua[:50]}")
    
    # Determine if this is a mobile user agent
    is_mobile = 'Mobile' in selected_ua or 'iPhone' in selected_ua or 'Android' in selected_ua
    
    # Build headers based on browser type and mobile detection
    if 'iPhone' in selected_ua:
        headers = {
            'User-Agent': selected_ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'sl-SI,sl;q=0.9,en-US;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
    elif 'Android' in selected_ua:
        headers = {
            'User-Agent': selected_ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'sl-SI,sl;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Charset': 'UTF-8,*;q=0.8',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none'
        }
    elif 'Firefox' in selected_ua:
        headers = {
            'User-Agent': selected_ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'sl-SI,sl;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Charset': 'UTF-8,*;q=0.8',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1'
        }
    else:  # Chrome-based
        mobile_header = '?1' if is_mobile else '?0'
        platform_header = '"Android"' if 'Android' in selected_ua else '"Linux"'
        
        headers = {
            'User-Agent': selected_ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'sl-SI,sl;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Charset': 'UTF-8,*;q=0.8',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'DNT': '1',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120"',
            'sec-ch-ua-mobile': mobile_header,
            'sec-ch-ua-platform': platform_header,
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1'
        }
    
    session = requests.Session()
    session.headers.update(headers)
    
    try:
        # First establish session by visiting homepage (helps bypass bot detection)
        try:
            homepage_response = session.get(BASE_URL, timeout=30)
            if debug_mode:
                print(f"[DEBUG] Homepage visit status: {homepage_response.status_code}")
            
            # Check for Cloudflare challenge on homepage
            if "One moment, please" in homepage_response.text:
                if debug_mode:
                    print(f"[DEBUG] Cloudflare challenge detected on homepage")
                raise Exception("Cloudflare bot detection active")
                
            # Wait like a human would before navigating (longer for production)
            delay = random.uniform(2, 5)
            if debug_mode:
                print(f"[DEBUG] Human-like delay: {delay:.1f}s")
            time.sleep(delay)
            
        except Exception as e:
            if debug_mode:
                print(f"[DEBUG] Homepage visit failed: {e}")
            # Continue anyway, but log the issue
        
        # Update headers for same-origin navigation
        session.headers.update({
            'Referer': BASE_URL,
            'Sec-Fetch-Site': 'same-origin'
        })
        
        # Enhanced retry mechanism with multiple strategies
        for attempt in range(5):  # Increased retry attempts
            try:
                if attempt == 1:
                    # Second attempt: Switch to mobile user agent
                    mobile_ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
                    session.headers.update({
                        'User-Agent': mobile_ua,
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'sl-SI,sl;q=0.9,en-US;q=0.8',
                    })
                    # Remove problematic headers for mobile
                    for header in ['sec-ch-ua', 'sec-ch-ua-mobile', 'sec-ch-ua-platform', 'Cache-Control', 'Pragma']:
                        session.headers.pop(header, None)
                elif attempt == 2:
                    # Third attempt: Older Firefox
                    session.headers.update({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    })
                elif attempt == 3:
                    # Fourth attempt: Very basic headers
                    session.headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1'
                    }
                elif attempt == 4:
                    # Fifth attempt: Very simple headers to avoid 415 errors
                    session.headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Accept-Encoding': 'gzip, deflate',
                        'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.3',
                        'Connection': 'keep-alive'
                    }
                
                # Progressive delay: longer waits for later attempts
                if attempt > 0:
                    # Exponential backoff with jitter
                    base_delay = 2 ** (attempt - 1)  # 1, 2, 4, 8 seconds base
                    jitter = random.uniform(0.5, 2.0)
                    delay = min(base_delay * jitter, 20)  # Cap at 20 seconds
                    if debug_mode:
                        print(f"[DEBUG] Retry attempt {attempt} delay: {delay:.1f}s")
                    time.sleep(delay)
                
                # Make the request with different timeout strategies
                timeout_val = 20 + (attempt * 5)  # Increase timeout for later attempts
                response = session.get(url_to_scrape, timeout=timeout_val, allow_redirects=True)
                
                # Enhanced Cloudflare detection
                cloudflare_indicators = [
                    "One moment, please",
                    "Please wait while your request is being verified",
                    "DDoS protection by Cloudflare",
                    "cf-browser-verification",
                    "Checking your browser",
                    "__cf_bm"
                ]
                
                is_cloudflare_challenge = any(indicator in response.text for indicator in cloudflare_indicators)
                
                if is_cloudflare_challenge:
                    if debug_mode:
                        print(f"[DEBUG] Cloudflare challenge detected on attempt {attempt + 1}")
                    if attempt == 4:  # Last attempt
                        raise Exception("Cloudflare bot detection preventing access")
                    continue
                
                # Check for successful response
                if response.status_code == 200:
                    content_type = response.headers.get('content-type', '').lower()
                    if debug_mode:
                        print(f"[DEBUG] Attempt {attempt + 1} - Response status: {response.status_code}, content-type: {content_type}, length: {len(response.content)}")
                    
                    if 'text/html' in content_type and len(response.content) > 1000:  # Ensure it's substantial content
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
                        if debug_mode:
                            print(f"[DEBUG] Invalid content: type={content_type}, length={len(response.content)}")
                        if attempt == 4:
                            raise Exception(f"Invalid content: {content_type}, length: {len(response.content)}")
                        continue
                elif response.status_code in [403, 415, 503]:  # Typical bot blocking codes including 415
                    if debug_mode:
                        print(f"[DEBUG] Bot blocking detected: HTTP {response.status_code}")
                    if attempt == 4:
                        raise Exception(f"Access denied: HTTP {response.status_code}")
                    continue
                else:
                    if debug_mode:
                        print(f"[DEBUG] HTTP {response.status_code}: {response.reason}")
                    if response.status_code >= 400:
                        if attempt == 4:
                            raise Exception(f"HTTP {response.status_code}: {response.reason}")
                        continue
                    response.raise_for_status()
                    
            except requests.exceptions.RequestException as e:
                if debug_mode:
                    print(f"[DEBUG] Request attempt {attempt + 1} failed: {e}")
                if attempt == 4:
                    raise Exception(f"All retry attempts failed. Last error: {e}")
                continue
        else:
            raise Exception("All retry attempts exhausted")
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

def scheduled_scrape_job():
    """
    Scrape job that runs on scheduled times (Saturday and Sunday at 23:00)
    Fetches only the current round data for Liga A and Liga B and saves to database
    """
    print(f"\n{'='*60}")
    print(f"[SCHEDULED SCRAPE] Starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    # Define leagues to scrape
    leagues = [
        {
            'id': 'liga_a',
            'name': 'Liga A',
            'url': 'https://www.lmn-radgona.si/index.php/ct-menu-item-7/razpored-liga-a'
        },
        {
            'id': 'liga_b',
            'name': 'Liga B',
            'url': 'https://www.lmn-radgona.si/index.php/2017-08-11-13-54-06/razpored-liga-b'
        }
    ]
    
    total_matches_scraped = 0
    total_matches_saved = 0
    
    for league in leagues:
        try:
            print(f"\n{'─'*60}")
            print(f"[{league['name']}] Starting scrape...")
            print(f"{'─'*60}")
            
            # Fetch only current round (fetch_all_rounds_data=False)
            page_matches, _, available_rounds, current_round_info = fetch_lmn_radgona_data(
                league['url'], 
                fetch_all_rounds_data=False
            )
            
            total_matches_scraped += len(page_matches)
            
            print(f"\n[{league['name']}] ✓ Scraped {len(page_matches)} matches from: {current_round_info['name']}")
            print(f"[{league['name']}] Available rounds: {len(available_rounds)}")
            
            # Display some match data
            if page_matches:
                print(f"\n[{league['name']}] Sample matches from {current_round_info['name']}:")
                for i, match in enumerate(page_matches[:3]):
                    print(f"  {i+1}. {match['home_team']} {match['score_str']} {match['away_team']} - {match['date_str']} {match['time']}")
                if len(page_matches) > 3:
                    print(f"  ... and {len(page_matches) - 3} more matches")
            
            # Save to database
            if DATABASE_AVAILABLE and page_matches:
                try:
                    print(f"\n[{league['name']}] Saving {len(page_matches)} matches to database...")
                    cache_matches(league['id'], current_round_info['url'], page_matches)
                    total_matches_saved += len(page_matches)
                    print(f"[{league['name']}] ✓ Successfully saved to database")
                except Exception as db_error:
                    print(f"[{league['name']}] DATABASE ERROR: {db_error}")
                    import traceback
                    traceback.print_exc()
            elif not DATABASE_AVAILABLE:
                print(f"\n[{league['name']}] Database not available - matches not saved")
            
            # Small delay between leagues to be respectful
            if league != leagues[-1]:  # Don't delay after last league
                delay = random.uniform(2, 4)
                print(f"\n[INFO] Waiting {delay:.1f}s before next league...")
                time.sleep(delay)
                
        except Exception as e:
            print(f"\n[{league['name']}] ERROR: Failed to scrape - {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*60}")
    print(f"[SCHEDULED SCRAPE] Completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[SUMMARY] Total matches scraped: {total_matches_scraped}")
    print(f"[SUMMARY] Total matches saved: {total_matches_saved}")
    print(f"{'='*60}\n")


def run_scheduler():
    """
    Runs the scheduler in a loop
    Schedules scraping for Saturday and Sunday at 23:00
    """
    # Initialize database connection pool if available
    if DATABASE_AVAILABLE:
        try:
            print("[DATABASE] Initializing database connection pool...")
            init_db_pool()
            init_db()
            print("[DATABASE] ✓ Database initialized successfully")
        except Exception as e:
            print(f"[DATABASE ERROR] Failed to initialize database: {e}")
            print("[WARNING] Continuing without database support")
    
    # Schedule for Saturday at 23:00
    schedule.every().saturday.at("23:00").do(scheduled_scrape_job)
    
    # Schedule for Sunday at 23:00
    schedule.every().sunday.at("23:00").do(scheduled_scrape_job)
    
    print("=" * 60)
    print("SCRAPER SCHEDULER STARTED")
    print("=" * 60)
    print(f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Schedule: Every Saturday and Sunday at 23:00")
    print(f"Target: Liga A + Liga B - Current round only")
    print(f"Database: {'✓ Enabled' if DATABASE_AVAILABLE else '✗ Disabled'}")
    print("=" * 60)
    print("\nWaiting for scheduled times...")
    print("(Press Ctrl+C to stop)\n")
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    except KeyboardInterrupt:
        print("\n\n[SCHEDULER] Stopped by user")


if __name__ == '__main__':
    import sys
    
    # Check if running in scheduler mode or test mode
    if len(sys.argv) > 1 and sys.argv[1] == '--schedule':
        # Production mode: run scheduler
        run_scheduler()
    elif len(sys.argv) > 1 and sys.argv[1] == '--test-now':
        # Test mode: run scrape immediately with database
        print("Running test scrape now...")
        if DATABASE_AVAILABLE:
            try:
                print("[DATABASE] Initializing database...")
                init_db_pool()
                init_db()
                print("[DATABASE] ✓ Database ready")
            except Exception as e:
                print(f"[DATABASE ERROR] {e}")
                print("[WARNING] Continuing without database")
        scheduled_scrape_job()
    else:
        # Default: show usage information
        print("=" * 60)
        print("LMN Radgona Scraper")
        print("=" * 60)
        print("\nUsage:")
        print("  python scraper_radgona.py --schedule    Start scheduler (runs Sat & Sun at 23:00)")
        print("  python scraper_radgona.py --test-now    Run scrape immediately (for testing)")
        print("\nScheduled times:")
        print("  - Saturday at 23:00")
        print("  - Sunday at 23:00")
        print("  - Scrapes only current round of Liga A + Liga B")
        print(f"  - Database: {'✓ Available' if DATABASE_AVAILABLE else '✗ Not available'}")
        print("=" * 60)
        
        # Quick test example (without database)
        print("\n--- QUICK TEST (fetching current round only, no database) ---")
        liga_a_main_results_url = "https://www.lmn-radgona.si/index.php/ct-menu-item-7/razpored-liga-a"
        page_m, _, avail_r, curr_r_info = fetch_lmn_radgona_data(liga_a_main_results_url, fetch_all_rounds_data=False)
        print(f"Current Round: {curr_r_info['name']}")
        print(f"Matches found: {len(page_m)}")
        print(f"Available rounds on page: {len(avail_r)}")
        if page_m:
            print(f"\nFirst match: {page_m[0]['home_team']} {page_m[0]['score_str']} {page_m[0]['away_team']}")