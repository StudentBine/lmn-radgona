#!/usr/bin/env python3

import database
from analyze_linki_ekipe import analyze_linki_ekipe

def import_missing_teams():
    """Import missing teams from linki_ekipe.txt"""
    print("=== UVOZ MANJKAJOČIH EKIP ===\n")
    
    try:
        database.init_db_pool()
        
        analysis = analyze_linki_ekipe()
        if not analysis:
            print("Napaka pri analizi ekip!")
            return False
        
        missing_teams = analysis['missing_teams']
        
        if not missing_teams:
            print("✅ Vse ekipe so že v bazi!")
            return True
        
        print(f"Uvažam {len(missing_teams)} manjkajočih ekip:")
        
        imported_count = 0
        
        with database.db_cursor() as cursor:
            for team in missing_teams:
                try:
                    cursor.execute(
                        "INSERT INTO teams (name, league_id) VALUES (%s, %s)",
                        (team['name'], team['league_id'])
                    )
                    print(f"✅ {team['name']} ({team['league_id']})")
                    imported_count += 1
                    
                except Exception as e:
                    print(f"❌ Napaka pri uvozu {team['name']}: {e}")
        
        print(f"\n🎯 Uspešno uvoženih: {imported_count} ekip")
        return imported_count > 0
        
    except Exception as e:
        print(f"Napaka: {e}")
        return False

if __name__ == "__main__":
    import_missing_teams()