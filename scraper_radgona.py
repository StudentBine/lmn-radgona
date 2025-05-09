import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse, parse_qs
from datetime import datetime

BASE_URL = "https://www.lmn-radgona.si"

def parse_slovene_date_from_header(date_str_full):
    """
    Parses a date string like 'Sobota, 03.05.2025' or 'Nedelja, 04.05.2025'
    into a datetime.date object. Returns None if parsing fails.
    """
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
    selected_round_info = {'name': "N/A", 'url': current_url}

    select_round_element = soup.find('select', id='select-round')
    if select_round_element:
        options = select_round_element.find_all('option')
        for option in options:
            round_name = option.get_text(strip=True)
            relative_url = option.get('value')
            if round_name and relative_url:
                full_url = urljoin(BASE_URL, relative_url)
                opt_data = {'name': round_name, 'url': full_url}
                round_options.append(opt_data)
                if option.has_attr('selected'):
                    selected_round_info = opt_data
    
    if selected_round_info['name'] == "N/A":
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


def fetch_lmn_radgona_data(url_to_scrape):
    """Fetches match results and available round options from the given URL."""
    match_results_list = []
    available_rounds = []
    current_round_info = {'name': "N/A", 'url': url_to_scrape}

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        print(f"Fetching data from: {url_to_scrape}")
        response = requests.get(url_to_scrape, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        available_rounds, current_round_info_from_select = extract_round_options_and_current(soup, url_to_scrape)
        if current_round_info_from_select['name'] != "N/A":
            current_round_info = current_round_info_from_select


        fixtures_table = soup.find('table', class_='fixtures-results')

        if not fixtures_table:
            print(f"Could not find the 'fixtures-results' table on {url_to_scrape}.")
            return match_results_list, available_rounds, current_round_info

        current_date_str_from_header = "N/A"
        
        for row in fixtures_table.find_all('tr', recursive=False):
            if 'sectiontableheader' in row.get('class', []):
                date_th = row.find('th')
                if date_th:
                    current_date_str_from_header = date_th.get_text(strip=True) if date_th.get_text(strip=True) else "Datum ni določen"
                continue

            if 'sectiontableentry1' in row.get('class', []) or \
               'sectiontableentry2' in row.get('class', []):
                
                cells = row.find_all('td', recursive=False)

                if len(cells) >= 10:
                    try:
                        match_time_abbr = cells[1].find('abbr', class_='dtstart')
                        match_time = match_time_abbr.get_text(strip=True) if match_time_abbr else "N/A"

                        home_team_span = cells[3].find('span')
                        home_team = home_team_span.get_text(strip=True) if home_team_span else "N/A"
                        
                        score_cell_link = cells[5].find('a')
                        score_span = score_cell_link.find('span', class_=re.compile(r'score.*')) if score_cell_link else None
                        
                        score = "N/P" 
                        if score_span:
                            score_raw = score_span.get_text(separator="").replace('\xa0', ' ').strip()
                            if any(char.isdigit() for char in score_raw) or "preloženo" in score_raw.lower():
                                score = score_raw
                            elif "_ - _" in score_raw : 
                                score = "N/P" 
                        elif score_cell_link and score_cell_link.get_text(strip=True) == "-":
                             score = "N/P"


                        away_team_span = cells[7].find('span')
                        away_team = away_team_span.get_text(strip=True) if away_team_span else "N/A"

                        venue_cell = cells[9].find('a')
                        venue = venue_cell.get_text(strip=True) if venue_cell else "N/A"
                        
                        parsed_date_obj = parse_slovene_date_from_header(current_date_str_from_header)

                        match_results_list.append({
                            'date_str': current_date_str_from_header, 
                            'date_obj': parsed_date_obj, 
                            'time': match_time,
                            'home_team': home_team,
                            'score': score,
                            'away_team': away_team,
                            'venue': venue
                        })
                    except AttributeError as e:
                        print(f"Skipping a row due to missing element (AttributeError): {e} in row: {row.prettify()[:200]}...")
                    except IndexError as e:
                        print(f"Skipping a row due to missing cell (IndexError): {e} in row: {row.prettify()[:200]}...")
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL {url_to_scrape}: {e}")
    except Exception as e:
        print(f"An error occurred during scraping {url_to_scrape}: {e}")
        import traceback
        traceback.print_exc()
            
    return match_results_list, available_rounds, current_round_info


if __name__ == '__main__':
    default_page_url = "https://www.lmn-radgona.si/index.php/ct-menu-item-7/razpored-liga-a"
    
    matches, rounds, current_round = fetch_lmn_radgona_data(default_page_url)
    
    print(f"\n--- Default Loaded Round ---")
    print(f"Name: {current_round['name']}, URL: {current_round['url']}")

    print(f"\n--- Rounds Available ({len(rounds)}) ---")
    for r_idx, r in enumerate(rounds):
        if r_idx < 3 or r_idx > len(rounds) - 4 :
             print(f"{r['name']}: {r['url']}")
        elif r_idx == 3:
            print("...")


    print(f"\n--- Matches for: {current_round['name']} ---")
    if matches:
        today_actual = datetime.now().date()
        print(f"(Actual Today: {today_actual.strftime('%A, %d.%m.%Y')})")
        for item in matches:
            date_status = ""
            if item['date_obj']:
                if item['date_obj'] == today_actual:
                    date_status = " (DANES)"
                elif item['date_obj'] < today_actual:
                    date_status = " (Preteklo)"
                else:
                    date_status = " (Prihodnje)"

            print(f"{item['date_str']}{date_status} @ {item['time']} [{item['venue']}]: {item['home_team']} {item['score']} {item['away_team']}")
    else:
        print("No match data scraped for the default round.")