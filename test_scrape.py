from curl_cffi import requests
import json
import re

url = "https://stockx.com/search/sneakers?s=jordan%201%20high%20og"
headers = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'accept-language': 'en-US,en;q=0.9',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

response = requests.get(url, headers=headers, impersonate="chrome120")

if response.status_code == 200:
    match_next = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', response.text)
    if match_next:
        data = json.loads(match_next.group(1))
        # inspect props
        try:
            results = data['props']['pageProps']['req']['appContext']['states']['query']['queries']
            with open("dump.json", "w") as f:
                json.dump(results, f, indent=2)
            print("Dumped queries to dump.json")
        except Exception as e:
            with open("dump.json", "w") as f:
                json.dump(data, f, indent=2)
            print("Dumped whole json to dump.json")
else:
    print(f"Failed: {response.status_code}")
