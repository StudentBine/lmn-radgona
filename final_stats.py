#!/usr/bin/env python3

import database

def final_stats():
    """Get final statistics of teams and players"""
    print("=== KONČNA STATISTIKA BAZE PODATKOV ===\n")
    
    try:
        database.init_db_pool()
        
        with database.db_cursor() as cursor:
            # Total counts
            cursor.execute("SELECT COUNT(*) as total FROM teams")
            total_teams = cursor.fetchone()['total']
            
            cursor.execute("SELECT COUNT(*) as total FROM players")
            total_players = cursor.fetchone()['total']
            
            print(f"🏆 SKUPAJ:")
            print(f"   📋 {total_teams} ekip")
            print(f"   👥 {total_players} igralcev")
            
            # By league
            cursor.execute("""
                SELECT t.league_id, COUNT(DISTINCT t.id) as teams, COUNT(p.id) as players
                FROM teams t 
                LEFT JOIN players p ON t.id = p.team_id 
                GROUP BY t.league_id 
                ORDER BY t.league_id
            """)
            league_stats = cursor.fetchall()
            
            print(f"\n📊 PO LIGAH:")
            for stat in league_stats:
                print(f"   {stat['league_id'].upper()}: {stat['teams']} ekip, {stat['players']} igralcev")
            
            # Top teams by player count
            cursor.execute("""
                SELECT t.name, t.league_id, COUNT(p.id) as player_count
                FROM teams t 
                LEFT JOIN players p ON t.id = p.team_id 
                GROUP BY t.id, t.name, t.league_id 
                ORDER BY player_count DESC
                LIMIT 10
            """)
            top_teams = cursor.fetchall()
            
            print(f"\n🥇 TOP 10 EKIP PO ŠTEVILU IGRALCEV:")
            for i, team in enumerate(top_teams, 1):
                print(f"   {i:2d}. {team['name']} ({team['league_id']}): {team['player_count']} igralcev")
        
    except Exception as e:
        print(f"Napaka: {e}")

if __name__ == "__main__":
    final_stats()