#!/usr/bin/env python3
"""
Debug web page structure
"""

import requests
from bs4 import BeautifulSoup

def debug_page_structure():
    """Debug the structure of a team page"""
    url = "https://www.lmn-radgona.si/ct-menu-item-7/2017-08-30-08-49-47/baren"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        print("=== PAGE TITLE ===")
        print(soup.title.text if soup.title else "No title")
        
        print("\n=== MAIN CONTENT STRUCTURE ===")
        
        # Look for main content div
        main_content = soup.find('div', class_='main') or soup.find('main') or soup.find('div', id='content')
        if main_content:
            print("Found main content area")
            
            # Look for tables
            tables = main_content.find_all('table')
            print(f"Found {len(tables)} tables")
            
            for i, table in enumerate(tables):
                print(f"\nTable {i+1}:")
                rows = table.find_all('tr')
                print(f"  {len(rows)} rows")
                if rows:
                    first_row = rows[0]
                    cells = first_row.find_all(['th', 'td'])
                    print(f"  First row has {len(cells)} cells:")
                    for j, cell in enumerate(cells[:5]):  # First 5 cells
                        print(f"    Cell {j+1}: {cell.get_text(strip=True)[:50]}")
        
        # Look for lists
        print(f"\n=== LISTS ===")
        lists = soup.find_all(['ul', 'ol'])
        print(f"Found {len(lists)} lists")
        
        for i, lst in enumerate(lists[:3]):  # First 3 lists
            items = lst.find_all('li')
            print(f"List {i+1}: {len(items)} items")
            for j, item in enumerate(items[:5]):  # First 5 items
                print(f"  Item {j+1}: {item.get_text(strip=True)[:50]}")
        
        # Look for divs with potential player info
        print(f"\n=== DIVS WITH NUMBERS ===")
        all_divs = soup.find_all('div')
        number_divs = []
        for div in all_divs:
            text = div.get_text(strip=True)
            if len(text) < 100 and any(char.isdigit() for char in text):
                number_divs.append(text)
        
        print(f"Found {len(number_divs)} divs with numbers:")
        for text in number_divs[:10]:  # First 10
            print(f"  {text}")
        
        # Save HTML for manual inspection
        with open('debug_baren_page.html', 'w', encoding='utf-8') as f:
            f.write(soup.prettify())
        print(f"\n💾 Saved HTML to debug_baren_page.html for manual inspection")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_page_structure()