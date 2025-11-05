#!/usr/bin/env python3
"""
Advanced anti-bot detection techniques for production environments
Tests multiple strategies to bypass Cloudflare protection
"""

import requests
import time
import random
from bs4 import BeautifulSoup

def get_rotating_user_agents():
    """Return a list of realistic user agents from different browsers and systems"""
    return [
        # Chrome on different systems
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        
        # Firefox on different systems
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0',
        'Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0',
        
        # Safari
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
        
        # Edge
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0'
    ]

def test_stealth_scraping():
    """Test stealth scraping techniques"""
    
    user_agents = get_rotating_user_agents()
    
    for attempt, user_agent in enumerate(user_agents):
        print(f"\n=== Attempt {attempt + 1}: {user_agent.split('/')[-1].split()[0]} ===")
        
        # Create fresh session for each attempt
        session = requests.Session()
        
        # Base headers that change per browser type
        if 'Firefox' in user_agent:
            headers = {
                'User-Agent': user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'sl-SI,sl;q=0.8,en-US;q=0.5,en;q=0.3',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1'
            }
        else:  # Chrome/Safari/Edge
            headers = {
                'User-Agent': user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'sl-SI,sl;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'sec-ch-ua': f'"Not_A Brand";v="8", "Chromium";v="120"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Linux"',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1'
            }
        
        try:
            session.headers.update(headers)
            
            # Step 1: Visit homepage with longer delay
            print("Visiting homepage...")
            homepage_response = session.get('https://www.lmn-radgona.si', timeout=30)
            print(f"Homepage status: {homepage_response.status_code}")
            
            if "One moment, please" in homepage_response.text:
                print("❌ Challenge on homepage")
                continue
                
            # Human-like delay
            delay = random.uniform(3, 7)
            print(f"Waiting {delay:.1f}s...")
            time.sleep(delay)
            
            # Step 2: Navigate to target with updated headers
            session.headers.update({
                'Referer': 'https://www.lmn-radgona.si',
                'Sec-Fetch-Site': 'same-origin'
            })
            
            print("Accessing Liga A page...")
            target_response = session.get(
                'https://www.lmn-radgona.si/index.php/ct-menu-item-7/razpored-liga-a',
                timeout=30
            )
            
            print(f"Status: {target_response.status_code}")
            print(f"Length: {len(target_response.text)}")
            
            if "One moment, please" in target_response.text:
                print("❌ Challenge on target page")
                continue
            
            # Check content
            soup = BeautifulSoup(target_response.text, 'html.parser')
            title = soup.find('title')
            print(f"Title: {title.get_text(strip=True) if title else 'No title'}")
            
            fixtures_table = soup.find('table', class_='fixtures-results')
            all_tables = soup.find_all('table')
            
            print(f"Tables: {len(all_tables)}, Fixtures: {fixtures_table is not None}")
            
            if fixtures_table:
                print("✅ SUCCESS! Found fixtures table")
                return True
            else:
                print("❌ No fixtures table")
                
        except Exception as e:
            print(f"❌ Error: {e}")
            
        # Wait between attempts to avoid rate limiting
        if attempt < len(user_agents) - 1:
            time.sleep(random.uniform(2, 5))
    
    return False

if __name__ == "__main__":
    success = test_stealth_scraping()
    print(f"\n🎯 Final result: {'SUCCESS' if success else 'FAILED'}")