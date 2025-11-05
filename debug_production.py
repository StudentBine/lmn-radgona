#!/usr/bin/env python3
"""
Debug script to test what the production scraper sees
"""
import requests
from bs4 import BeautifulSoup

def test_production_scraper():
    url = "https://www.lmn-radgona.si/index.php/ct-menu-item-7/razpored-liga-a"
    
    # Use the exact same headers as the scraper
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'sl-SI,sl;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'no-cache'
    }
    
    print(f"Testing URL: {url}")
    print("="*60)
    
    try:
        print("Making request...")
        response = requests.get(url, headers=headers, timeout=15)
        print(f"Status Code: {response.status_code}")
        print(f"Content Length: {len(response.text)}")
        print(f"Content Type: {response.headers.get('content-type', 'unknown')}")
        
        if response.status_code != 200:
            print(f"ERROR: Non-200 status code: {response.status_code}")
            return False
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Check for fixtures-results table specifically
        fixtures_table = soup.find('table', class_='fixtures-results')
        print(f"\nFixtures-results table found: {fixtures_table is not None}")
        
        # Show all tables
        all_tables = soup.find_all('table')
        print(f"Total tables found: {len(all_tables)}")
        
        for i, table in enumerate(all_tables):
            classes = table.get('class', [])
            table_id = table.get('id', 'no-id')
            print(f"  Table {i+1}: classes={classes}, id={table_id}")
            
            # If this is the fixtures table, show some content
            if 'fixtures-results' in classes:
                rows = table.find_all('tr')
                print(f"    → Fixtures table has {len(rows)} rows")
                
        # Check page title to make sure we got the right page
        title = soup.find('title')
        if title:
            print(f"\nPage title: {title.get_text(strip=True)}")
            
        # Look for any error messages or redirects
        if "error" in response.text.lower() or "404" in response.text:
            print("WARNING: Page content might contain errors")
            
        return fixtures_table is not None
        
    except Exception as e:
        print(f"ERROR: {e}")
        return False

if __name__ == "__main__":
    success = test_production_scraper()
    print(f"\nTest result: {'SUCCESS' if success else 'FAILED'}")