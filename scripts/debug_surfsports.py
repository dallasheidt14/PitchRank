"""Debug script to inspect HTML structure"""
import requests
from bs4 import BeautifulSoup
import re

url = "https://public.totalglobalsports.com/public/event/4067/schedules-standings"
response = requests.get(url)
print(f"Status: {response.status_code}")
print(f"Content length: {len(response.text)}")

soup = BeautifulSoup(response.text, 'html.parser')

# Check for tables
tables = soup.find_all('table')
print(f"\nFound {len(tables)} <table> elements")

# Check for divs with table-like structure
divs_with_tables = soup.find_all('div', class_=re.compile(r'table', re.I))
print(f"Found {len(divs_with_tables)} divs with 'table' in class")

# Look for schedule links
all_links = soup.find_all('a', href=True)
schedule_links = [link for link in all_links if '/schedules/' in link.get('href', '')]
print(f"\nFound {len(schedule_links)} links with '/schedules/' in href")

for link in schedule_links[:5]:
    print(f"  {link.get('href')}")

# Save HTML to file for inspection
with open('data/debug_surfsports.html', 'w', encoding='utf-8') as f:
    f.write(response.text)
print(f"\nSaved HTML to data/debug_surfsports.html")












