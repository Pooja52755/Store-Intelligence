import urllib.request
import json

try:
    url = "http://127.0.0.1:8000/stores/STORE_BLR_002/metrics"
    with urllib.request.urlopen(url) as response:
        html = response.read().decode('utf-8')
        data = json.loads(html)
        print("API Response:")
        print(json.dumps(data, indent=2))
except Exception as e:
    print(f"Error querying API: {e}")
