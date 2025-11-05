#!/usr/bin/env python3
"""
Fallback scraper using alternative techniques
This will be used if the main scraper fails due to bot detection
"""

import requests
import time
import random
from bs4 import BeautifulSoup
import os

def fallback_scrape_attempt(url):
    """Alternative scraping approach with different techniques"""
    
    # Try mobile user agent (sometimes less scrutinized)
    mobile_headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'sl-SI,sl;q=0.9,en-US;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    session = requests.Session()
    session.headers.update(mobile_headers)
    
    try:
        print("Trying mobile user agent approach...")
        
        # Direct request to target page (no homepage visit)
        response = session.get(url, timeout=25)
        
        if "One moment, please" not in response.text and response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            fixtures_table = soup.find('table', class_='fixtures-results')
            
            if fixtures_table:
                print("✅ Mobile approach SUCCESS!")
                return response.text
                
        print("❌ Mobile approach failed")
        
    except Exception as e:
        print(f"❌ Mobile approach error: {e}")
    
    return None

def get_fallback_data():
    """Get data using fallback method"""
    url = "https://www.lmn-radgona.si/index.php/ct-menu-item-7/razpored-liga-a"
    
    # Try the fallback approach
    content = fallback_scrape_attempt(url)
    
    if content:
        return {
            'success': True,
            'content_length': len(content),
            'method': 'mobile_fallback'
        }
    else:
        return {
            'success': False,
            'error': 'All fallback methods failed'
        }

if __name__ == "__main__":
    result = get_fallback_data()
    print(f"Result: {result}")