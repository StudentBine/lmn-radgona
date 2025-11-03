#!/usr/bin/env python3

import database

def analyze_linki_ekipe():
    """Analyze teams from linki_ekipe.txt and current database"""
    print("=== ANALIZA EKIP IZ LINKI_EKIPE.TXT ===\n")
    
    try:
        database.init_db_pool()
        
        # Read links from file
        teams_from_file = []
        
        with open('linki_ekipe.txt', 'r', encoding='utf-8') as file:
            current_league = 'liga_a'  # Default to Liga A
            
            for line in file:
                line = line.strip()
                
                if 'b Ligo:' in line or 'Liga B:' in line or 'liga_b' in line.lower():
                    current_league = 'liga_b'
                    continue
                    
                if line.startswith('http'):
                    # Extract team name from URL
                    team_slug = line.split('/')[-1]
                    
                    # Convert slug to proper team name
                    team_name_mapping = {
                        'baren': 'Baren',
                        'dinamo-radgona': 'Dinamo Radgona',
                        'ivanjsevska-slatina': 'Ivanjševska slatina',
                        'kapela': 'Kapela',
                        'lesane': 'Lešane',
                        'lokavec': 'Lokavec',
                        'negova': 'Negova',
                        'oceslavci': 'Očeslavci',
                        'plitvica': 'Plitvica',
                        'podgrad': 'Podgrad',
                        'radenska': 'Radenska',
                        'spodnja-scavnica': 'Spodnja Ščavnica',
                        'stari-hrast': 'Stari hrast',
                        'tiha-voda': 'Tiha voda',
                        'bumefekt': 'Bumefekt',
                        'cresnjevci': 'Črešnjevci',
                        'grabonos': 'Grabonoš',
                        'hrastko': 'Hrastko',
                        'ihova': 'Ihova',
                        'mahovci': 'Mahovci',
                        'police': 'Police',
                        'porkys': 'Porkys',
                        'segovci': 'Segovci',
                        'stavesinci': 'Stavešinci',
                        'senekar': 'Šenekar',
                        'vrabel': 'Vrabel',
                        'zoro': 'Zoro'
                    }
                    
                    team_name = team_name_mapping.get(team_slug, team_slug.replace('-', ' ').title())
                    teams_from_file.append({
                        'name': team_name,
                        'league_id': current_league,
                        'url': line,
                        'slug': team_slug
                    })
        
        print(f"Najdenih {len(teams_from_file)} ekip iz linki_ekipe.txt:")
        liga_a_count = sum(1 for t in teams_from_file if t['league_id'] == 'liga_a')
        liga_b_count = sum(1 for t in teams_from_file if t['league_id'] == 'liga_b')
        print(f"- Liga A: {liga_a_count} ekip")
        print(f"- Liga B: {liga_b_count} ekip")
        
        # Check existing teams in database
        with database.db_cursor() as cursor:
            cursor.execute("SELECT name, league_id FROM teams ORDER BY league_id, name")
            existing_teams = cursor.fetchall()
            
        print(f"\nTrenutno v bazi: {len(existing_teams)} ekip")
        
        # Find missing teams
        missing_teams = []
        existing_team_keys = {(team['name'], team['league_id']) for team in existing_teams}
        
        for team in teams_from_file:
            if (team['name'], team['league_id']) not in existing_team_keys:
                missing_teams.append(team)
        
        print(f"\nManjkajoče ekipe: {len(missing_teams)}")
        for team in missing_teams:
            print(f"- {team['name']} ({team['league_id']})")
        
        return {
            'teams_from_file': teams_from_file,
            'existing_teams': existing_teams,
            'missing_teams': missing_teams
        }
        
    except Exception as e:
        print(f"Napaka: {e}")
        return None

if __name__ == "__main__":
    analyze_linki_ekipe()