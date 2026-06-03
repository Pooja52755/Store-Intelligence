import urllib.request
import json

try:
    url = "http://127.0.0.1:8000/runs?store_id=STORE_BLR_002"
    with urllib.request.urlopen(url) as response:
        html = response.read().decode('utf-8')
        data = json.loads(html)
        print("API runs response:")
        print(json.dumps(data, indent=2))
except Exception as e:
    print(f"Error: {e}")
