#!/usr/bin/env python3
"""
Advanced scraper to bypass Cloudflare bot detection
Uses selenium-like headers and behavior patterns
"""

import requests
import time
import random
from bs4 import BeautifulSoup
from urllib.parse import urljoin

def advanced_scrape_test():
    """Test advanced scraping techniques to bypass bot detection"""
    
    # Use more sophisticated browser simulation
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'sl-SI,sl;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
    }
    
    session = requests.Session()
    
    # Step 1: Visit homepage and wait (simulate human behavior)
    print("Step 1: Visiting homepage...")
    try:
        homepage_url = "https://www.lmn-radgona.si"
        session.headers.update(headers)
        
        homepage_response = session.get(homepage_url, timeout=20)
        print(f"Homepage status: {homepage_response.status_code}")
        
        if "One moment, please" in homepage_response.text:
            print("❌ Cloudflare challenge detected on homepage")
            return False
            
        # Wait like a human would
        time.sleep(random.uniform(2, 4))
        
    except Exception as e:
        print(f"Homepage visit failed: {e}")
        return False
    
    # Step 2: Try to access the target page
    print("Step 2: Accessing Liga A page...")
    try:
        target_url = "https://www.lmn-radgona.si/index.php/ct-menu-item-7/razpored-liga-a"
        
        # Update headers for navigation
        session.headers.update({
            'Referer': homepage_url,
            'Sec-Fetch-Site': 'same-origin'
        })
        
        response = session.get(target_url, timeout=20)
        print(f"Target page status: {response.status_code}")
        print(f"Content length: {len(response.text)}")
        
        # Check for Cloudflare challenge
        if "One moment, please" in response.text:
            print("❌ Cloudflare challenge detected on target page")
            print("First 500 chars:", response.text[:500])
            return False
        
        # Check for content
        soup = BeautifulSoup(response.text, 'html.parser')
        title = soup.find('title')
        print(f"Page title: {title.get_text(strip=True) if title else 'No title'}")
        
        fixtures_table = soup.find('table', class_='fixtures-results')
        all_tables = soup.find_all('table')
        
        print(f"Tables found: {len(all_tables)}")
        print(f"Fixtures table found: {fixtures_table is not None}")
        
        if fixtures_table:
            print("✅ SUCCESS! Found fixtures table")
            return True
        else:
            print("❌ No fixtures table found")
            if len(all_tables) == 0:
                print("No tables at all - might still be challenge page")
            return False
            
    except Exception as e:
        print(f"Target page access failed: {e}")
        return False

if __name__ == "__main__":
    success = advanced_scrape_test()
    print(f"\nResult: {'SUCCESS' if success else 'FAILED'}")