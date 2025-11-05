#!/usr/bin/env python3
"""
Test the current scraper with the exact same configuration as production
"""

import sys
import os

# Add the current directory to path to import the scraper
sys.path.insert(0, '/home/omarchb/Documents/Github/lmn-radgona')

from scraper_radgona import fetch_lmn_radgona_data

def test_scraper():
    print("Testing scraper with production configuration...")
    print("="*60)
    
    # Enable debug mode
    os.environ['SCRAPER_DEBUG'] = 'true'
    
    # Test the same URL that's failing in production
    url = "https://www.lmn-radgona.si/index.php/ct-menu-item-7/razpored-liga-a"
    
    try:
        result = fetch_lmn_radgona_data(url)
        
        print(f"\nScraper result:")
        
        if isinstance(result, tuple) and len(result) >= 4:
            page_matches, all_data, available_rounds, current_round_info = result
            print(f"  - Page matches: {len(page_matches) if page_matches else 0}")
            print(f"  - Available rounds: {len(available_rounds) if available_rounds else 0}")
            print(f"  - Current round: {current_round_info}")
            
            if page_matches:
                print(f"  - First match: {page_matches[0]}")
                return True
            else:
                print("  - No matches found")
                return False
        else:
            print(f"  - Unexpected result format: {result}")
            return False
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_scraper()
    print(f"\nTest result: {'SUCCESS' if success else 'FAILED'}")