import requests
import json

PREZZO_MIN = 30
PREZZO_MAX = 80
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "it-IT,it;q=0.9",
}

def test_vinted():
    print("\n--- Testing Vinted ---")
    keyword = "ram 16gb"
    url = f"https://www.vinted.it/api/v2/catalog/items?search_text={keyword}&price_from={PREZZO_MIN}&price_to={PREZZO_MAX}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            items = data.get("items", [])
            print(f"Found {len(items)} items")
        else:
            print(f"Response: {r.text[:200]}")
    except Exception as e:
        print(f"Error: {e}")

def test_wallapop():
    print("\n--- Testing Wallapop ---")
    url = f"https://api.wallapop.com/api/v3/general/search?keywords=ram+16gb&min_sale_price={PREZZO_MIN}&max_sale_price={PREZZO_MAX}&country_code=IT"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            items = data.get("data", {}).get("section", {}).get("payload", {}).get("items", [])
            print(f"Found {len(items)} items")
        else:
            print(f"Response: {r.text[:200]}")
    except Exception as e:
        print(f"Error: {e}")

def test_subito():
    print("\n--- Testing Subito ---")
    url = f"https://www.subito.it/hades/v1/search/items?q=ram+16gb&ps={PREZZO_MIN}&pe={PREZZO_MAX}&c=28&sort=datedesc&lim=50"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            items = data.get("ads", [])
            print(f"Found {len(items)} items")
        else:
            print(f"Response: {r.text[:200]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_vinted()
    test_wallapop()
    test_subito()
