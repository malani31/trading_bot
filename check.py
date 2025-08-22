import requests
import hmac, hashlib, time, json

API_KEY = "8tvCQ00Kw3gFmaEsz3S9QnkG3y4yQL"
API_SECRET = "wkvOhPgb96BBQq7RinPajpH7vNiMGgy6iSISu7FbP7P4kHPf7GwUZMSs0Lnt"
BASE_URL = "https://api.delta.exchange"

def generate_signature(method, path, timestamp, query="", body=""):
    message = method + timestamp + path + query + body
    return hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

timestamp = str(int(time.time()))
path = "/v2/history/candles"
query = "?symbol=BTCUSD&resolution=15m&start=1750651200&end=1750654800"
body = ""
signature = generate_signature("GET", path, timestamp, query, body)

headers = {
    "api-key": API_KEY,
    "timestamp": timestamp,
    "signature": signature
}

r = requests.get(BASE_URL + path, headers=headers, params={})
print(r.status_code, r.text)
