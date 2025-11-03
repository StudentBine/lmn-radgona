#!/usr/bin/env python3
"""
Test different team URL
"""

import requests
from bs4 import BeautifulSoup

def test_different_url():
    """Test different team URL structure"""
    # Try Liga B team
    url = "https://www.lmn-radgona.si/2017-08-11-13-54-06/2017-08-30-09-01-58/bumefekt"
    
    print(f"Testing Liga B team: {url}")
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        print("=== PAGE TITLE ===")
        print(soup.title.text if soup.title else "No title")
        
        print("\n=== LOOKING FOR PLAYER LISTS ===")
        
        # Look for specific player indicators
        text_content = soup.get_text()
        
        # Look for jersey numbers followed by names
        import re
        
        # Pattern for players: number followed by name
        player_patterns = [
            r'(\d{1,2})\.?\s+([A-ZČŠŽĐĆ][a-zčšžđć]+(?:\s+[A-ZČŠŽĐĆ][a-zčšžđć]+)+)',
        ]
        
        found_players = []
        for pattern in player_patterns:
            matches = re.findall(pattern, text_content)
            for match in matches:
                number = int(match[0])
                name = match[1].strip()
                if 1 <= number <= 99 and len(name) > 2:
                    found_players.append(f"{number}. {name}")
        
        if found_players:
            print(f"Found {len(found_players)} potential players:")
            for player in found_players[:10]:
                print(f"  {player}")
        else:
            print("No players found with current patterns")
            
        # Look for tables that might contain players
        tables = soup.find_all('table')
        print(f"\nFound {len(tables)} tables")
        
        for i, table in enumerate(tables):
            print(f"\nTable {i+1} content preview:")
            rows = table.find_all('tr')
            for j, row in enumerate(rows[:5]):  # First 5 rows
                cells = row.find_all(['td', 'th'])
                row_text = " | ".join([cell.get_text(strip=True) for cell in cells])
                print(f"  Row {j+1}: {row_text[:100]}")
                
        # Save for inspection
        with open('debug_bumefekt_page.html', 'w', encoding='utf-8') as f:
            f.write(soup.prettify())
        print(f"\n💾 Saved HTML to debug_bumefekt_page.html")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_different_url()