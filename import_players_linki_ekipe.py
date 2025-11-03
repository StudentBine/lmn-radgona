#!/usr/bin/env python3
"""
Player importer using linki_ekipe.txt
"""

import requests
from bs4 import BeautifulSoup
import time
import database
import re
from urllib.parse import urljoin
from analyze_linki_ekipe import analyze_linki_ekipe

class LinkiEkipePlayerImporter:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def scrape_team_players(self, url, team_name):
        """Scrape players from team URL"""
        players = []
        
        try:
            print(f"  📡 Scraping: {url}")
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Method 1: Look for <span class="playername"> elements (LMN specific)
            player_spans = soup.find_all('span', class_='playername')
            if player_spans:
                print(f"    Found {len(player_spans)} playername spans")
                for i, span in enumerate(player_spans, 1):
                    player_name = span.get_text(strip=True)
                    if player_name and len(player_name) > 2:
                        players.append({
                            'name': player_name,
                            'jersey_number': i  # Sequential numbering
                        })
            
            # Method 2: Look for tables with player data (fallback)
            if not players:
                tables = soup.find_all('table')
                for table in tables:
                    rows = table.find_all('tr')
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        if len(cells) >= 2:
                            player_info = self.extract_player_from_row(cells)
                            if player_info:
                                players.append(player_info)
            
            # Method 3: Look for div containers with player info (fallback)
            if not players:
                player_containers = soup.find_all('div', class_=re.compile(r'player|member|igralec', re.I))
                for container in player_containers:
                    player_info = self.extract_player_from_div(container)
                    if player_info:
                        players.append(player_info)
            
            # Method 4: Look for any span with player-like names
            if not players:
                all_spans = soup.find_all('span')
                for span in all_spans:
                    text = span.get_text(strip=True)
                    # Check if it looks like a player name (First Last format)
                    if (len(text.split()) >= 2 and 
                        len(text) > 4 and len(text) < 50 and
                        re.match(r'^[A-ZČŠŽĐĆ][a-zčšžđć]+\s+[A-ZČŠŽĐĆ][a-zčšžđć]+', text) and
                        not any(word in text.lower() for word in ['ekipa', 'team', 'liga', 'krog', 'rezultat'])):
                        
                        players.append({
                            'name': text,
                            'jersey_number': len(players) + 1
                        })
            
            # Remove duplicates
            unique_players = []
            seen = set()
            for player in players:
                key = player['name'].lower()
                if key not in seen:
                    seen.add(key)
                    unique_players.append(player)
            
            return unique_players
            
        except requests.exceptions.RequestException as e:
            print(f"    ❌ Network error: {e}")
        except Exception as e:
            print(f"    ❌ Parse error: {e}")
            
        return []

    def extract_player_from_row(self, cells):
        """Extract player info from table row"""
        try:
            # Method 1: Look for jersey number followed by name
            for i, cell in enumerate(cells):
                text = cell.get_text(strip=True)
                
                # Look for jersey number
                number_match = re.match(r'^(\d{1,2})\.?\s*$', text)
                if number_match and i + 1 < len(cells):
                    jersey_number = int(number_match.group(1))
                    if 1 <= jersey_number <= 99:
                        name_cell = cells[i + 1]
                        player_name = name_cell.get_text(strip=True)
                        
                        # Clean name
                        player_name = re.sub(r'\s+', ' ', player_name).strip()
                        player_name = re.sub(r'\([^)]*\)', '', player_name).strip()  # Remove parentheses
                        
                        if len(player_name) > 2 and not re.match(r'^\d+$', player_name):
                            return {
                                'name': player_name,
                                'jersey_number': jersey_number
                            }
            
            # Method 2: Look for player names in specific columns (LMN structure)
            # Check if this looks like a player row (has name and age pattern)
            if len(cells) >= 5:
                # LMN structure: empty | empty | PlayerName | empty | (age) | stats...
                name_cell = cells[2] if len(cells) > 2 else None
                age_cell = cells[4] if len(cells) > 4 else None
                
                if name_cell and age_cell:
                    player_name = name_cell.get_text(strip=True)
                    age_text = age_cell.get_text(strip=True)
                    
                    # Check if age_text looks like "(number)"
                    age_match = re.match(r'\((\d+)\)', age_text)
                    
                    if (player_name and age_match and 
                        len(player_name) > 2 and 
                        not re.match(r'^\d+$', player_name) and
                        player_name not in ['Igralec', 'Name', 'Player', 'Starost']):
                        
                        # Generate jersey number (since LMN doesn't seem to have them)
                        # Use a hash of the name to generate consistent numbers
                        jersey_number = (hash(player_name) % 98) + 1
                        
                        return {
                            'name': player_name,
                            'jersey_number': jersey_number
                        }
                            
        except Exception:
            pass
            
        return None

    def extract_player_from_div(self, div):
        """Extract player info from div element"""
        try:
            text = div.get_text(strip=True)
            return self.extract_player_from_text(text)
        except:
            return None

    def extract_player_from_text(self, text):
        """Extract player from single text string"""
        # Pattern: "Number. FirstName LastName" or "Number FirstName LastName"
        patterns = [
            r'^(\d{1,2})\.?\s+([A-ZČŠŽĐĆ][a-zčšžđć]+(?:\s+[A-ZČŠŽĐĆ][a-zčšžđć]+)+)',
            r'(\d{1,2})\s+([A-ZČŠŽĐĆ][a-zčšžđć]+\s+[A-ZČŠŽĐĆ][a-zčšžđć]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text.strip())
            if match:
                try:
                    jersey_number = int(match.group(1))
                    player_name = match.group(2).strip()
                    
                    # Clean name
                    player_name = re.sub(r'\([^)]*\)', '', player_name)  # Remove parentheses
                    player_name = re.sub(r'\s+', ' ', player_name).strip()
                    
                    if 1 <= jersey_number <= 99 and len(player_name) > 2:
                        return {
                            'name': player_name,
                            'jersey_number': jersey_number
                        }
                except:
                    continue
                    
        return None

    def extract_players_from_full_text(self, text):
        """Extract all players from full text using patterns"""
        players = []
        
        # Multiple patterns for finding players
        patterns = [
            r'(\d{1,2})\.?\s+([A-ZČŠŽĐĆ][a-zčšžđć]+(?:\s+[A-ZČŠŽĐĆ][a-zčšžđć]+)+)',
            r'(\d{1,2})\s+([A-ZČŠŽĐĆ][a-zčšžđć]+\s+[A-ZČŠŽĐĆ][a-zčšžđć]+)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.MULTILINE)
            for match in matches:
                try:
                    jersey_number = int(match[0])
                    player_name = match[1].strip()
                    
                    # Clean name
                    player_name = re.sub(r'\([^)]*\)', '', player_name)
                    player_name = re.sub(r'\s+', ' ', player_name).strip()
                    
                    if 1 <= jersey_number <= 99 and len(player_name) > 2:
                        players.append({
                            'name': player_name,
                            'jersey_number': jersey_number
                        })
                except:
                    continue
                    
        return players

    def import_all_players(self):
        """Import all players from linki_ekipe.txt"""
        database.init_db_pool()
        
        # Get teams from linki_ekipe.txt
        analysis = analyze_linki_ekipe()
        if not analysis:
            print("❌ Napaka pri analizi ekip!")
            return
            
        teams = analysis['teams_from_file']
        
        total_imported = 0
        total_skipped = 0
        total_errors = 0
        
        print(f"🚀 Začenjam uvoz igralcev za {len(teams)} ekip...\n")
        
        for i, team_data in enumerate(teams, 1):
            print(f"[{i}/{len(teams)}] {team_data['name']} ({team_data['league_id']})")
            
            try:
                # Get team from database
                with database.db_cursor() as cursor:
                    cursor.execute(
                        "SELECT id FROM teams WHERE name = %s AND league_id = %s",
                        (team_data['name'], team_data['league_id'])
                    )
                    team = cursor.fetchone()
                    
                    if not team:
                        print(f"  ❌ Ekipa ni najdena v bazi!")
                        total_errors += 1
                        continue
                        
                    team_id = team['id']
                
                # Scrape players
                players = self.scrape_team_players(team_data['url'], team_data['name'])
                
                if not players:
                    print(f"  ⚠️  Ni najdenih igralcev")
                    continue
                
                print(f"  📋 Najdenih {len(players)} igralcev")
                
                # Import players
                imported_count = 0
                skipped_count = 0
                
                with database.db_cursor() as cursor:
                    for player in players:
                        # Check if player already exists
                        cursor.execute(
                            "SELECT id FROM players WHERE name = %s AND team_id = %s",
                            (player['name'], team_id)
                        )
                        existing = cursor.fetchone()
                        
                        if existing:
                            skipped_count += 1
                            continue
                            
                        # Check if jersey number is available
                        cursor.execute(
                            "SELECT id FROM players WHERE jersey_number = %s AND team_id = %s",
                            (player['jersey_number'], team_id)
                        )
                        jersey_taken = cursor.fetchone()
                        
                        if jersey_taken:
                            # Find next available number
                            cursor.execute(
                                "SELECT COALESCE(MAX(jersey_number), 0) + 1 as next_number FROM players WHERE team_id = %s",
                                (team_id,)
                            )
                            next_number = cursor.fetchone()['next_number']
                            player['jersey_number'] = next_number
                        
                        # Insert player
                        cursor.execute(
                            "INSERT INTO players (name, team_id, jersey_number) VALUES (%s, %s, %s)",
                            (player['name'], team_id, player['jersey_number'])
                        )
                        imported_count += 1
                
                print(f"  ✅ Uvoženih: {imported_count}, Preskočenih: {skipped_count}")
                total_imported += imported_count
                total_skipped += skipped_count
                
            except Exception as e:
                print(f"  ❌ Napaka: {e}")
                total_errors += 1
                
            # Small delay between requests
            time.sleep(1)
            
        print(f"\n🎯 KONČANO:")
        print(f"   Uvoženih igralcev: {total_imported}")
        print(f"   Preskočenih: {total_skipped}")
        print(f"   Napak: {total_errors}")

def main():
    importer = LinkiEkipePlayerImporter()
    importer.import_all_players()

if __name__ == "__main__":
    main()