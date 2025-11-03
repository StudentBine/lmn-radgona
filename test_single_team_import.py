#!/usr/bin/env python3
"""
Test player import for single team
"""

from import_players_linki_ekipe import LinkiEkipePlayerImporter
import database

def test_single_team():
    """Test import for single team"""
    print("=== TEST UVOZA ZA ENO EKIPO ===\n")
    
    database.init_db_pool()
    importer = LinkiEkipePlayerImporter()
    
    # Test with Bumefekt (Liga B team)
    test_url = "https://www.lmn-radgona.si/2017-08-11-13-54-06/2017-08-30-09-01-58/bumefekt"
    
    print(f"Testiram uvoz za ekipo Bumefekt (Liga B)")
    print(f"URL: {test_url}\n")
    
    players = importer.scrape_team_players(test_url, "Bumefekt")
    
    if players:
        print(f"✅ Najdenih {len(players)} igralcev:")
        for player in players[:10]:  # Show first 10
            print(f"  {player['jersey_number']}. {player['name']}")
        if len(players) > 10:
            print(f"  ... in še {len(players) - 10} drugih")
    else:
        print("❌ Ni najdenih igralcev")
    
    return players

if __name__ == "__main__":
    test_single_team()