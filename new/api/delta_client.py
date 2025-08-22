# your_trading_bot/api/delta_client.py
import requests
import hmac
import hashlib
import json
import time
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone
from urllib.parse import urlencode
# sys.path.append('/Users/princemalani/Desktop/sem 5/my_bot')
import config
# print("Using config from:", config.API_KEY)  # Debugging line to check which config is being used

class DeltaAPIClient:
    def __init__(self, api_key, api_secret, base_url):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.product_id_cache = {}
        self.product_details_cache = {}
        self.LOT_SIZE_BTC = config.LOT_SIZE_BTC  # Use the constant from the imported config module
        # Use the constant from the imported config module
       

    def _generate_signature(self, method:str, path:str, timestamp:str,query_params: str = '', body=None):
        """Generates the HMAC-SHA256 signature for Delta Exchange API requests."""
        # message = f"{method}{path}{str(expires)}"
        # 1. Start with method + timestamp + path
        prehash_string = f"{method}{timestamp}{path}"
        # 2. Add query_params (must be an empty string if no params, not omitted)
        prehash_string += query_params # query_params should be pre-formatted like "?param1=val1&param2=val2"

        # 3. Add body (payload). Must be an empty string if no body for POST/PUT, or for GET.
        # Documentation shows `payload = ''` for GET, and actual JSON string for POST.
        if body:
            prehash_string += json.dumps(body) # <--- NO separators=(',', ':')
        else:
            prehash_string += ""

        # Encode the *final* concatenated prehash string to bytes
        # Encode the secret to bytes
        signature = hmac.new(self.api_secret.encode('utf-8'), prehash_string.encode('utf-8'), hashlib.sha256).hexdigest()
        return signature


    def _send_request(self, method, path, params=None, data=None):
        """Helper to send signed requests to Delta Exchange API."""

        timestamp_str = str(int(datetime.now(timezone.utc).timestamp()))


        query_string_for_signature = ''
        if params:
            # IMPORTANT: Use urlencode for the query string used in the signature!
            # It will also sort parameters alphabetically, which is good for consistency.
            query_string_for_signature = urlencode(params)
            # Add a '?' prefix only if there are actual query parameters
            if query_string_for_signature:
                query_string_for_signature = '?' + query_string_for_signature

        # Prepare body for signature (pass original dict)
        body_for_signature = data

        # Generate signature
        signature = self._generate_signature(
            method,
            path,
            timestamp_str,
            query_string_for_signature,  # Pass the URL-encoded query string for signature
            body_for_signature
        )

        req_headers = {
            'api-key': self.api_key,
            'timestamp': timestamp_str,
            'signature': signature,
            'User-Agent': 'python-delta-client',
            'Content-Type': 'application/json'
        }

        request_url = f"{self.base_url}{path}"

        # For the actual HTTP request, 'requests' handles the params argument correctly,
        # so you can pass the 'params' dictionary directly.
        # It will handle the URL encoding and appending '?' for the actual URL.

        # Print for debugging (optional but helpful)
        print(f"Sending {method} request to {request_url} with params: {params} (for URL)")
        print(f"Headers: {req_headers}")
        print(f"Body : {data}")
        print(f"Prehash String components: Method='{method}', Timestamp='{timestamp_str}', Path='{path}', Query='{query_string_for_signature}', Body='{json.dumps(data, separators=(',', ':')) if data else ''}'")
        # Conditional Content-Type header
        if method.upper() in ['POST', 'PUT'] or (method.upper() == 'DELETE' and body is not None):
            req_headers['Content-Type'] = 'application/json'

        try:
            if method == 'GET':
                # Pass params dict directly; requests will URL-encode it for the actual request
                response = requests.get(request_url, params=params, headers=req_headers, timeout=(3, 27))
            elif method == 'POST':
                response = requests.post(request_url, json=data, headers=req_headers, timeout=(3, 27))
            elif method == 'PUT':
                response = requests.put(request_url, json=data, headers=req_headers, timeout=(3, 27))
            elif method == 'DELETE':
                response = requests.delete(request_url,json=data, headers=req_headers, timeout=(3, 27))
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            print(f"HTTP Error: {e.response.status_code} - {e.response.text}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Request Error: {e}")
            return None
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            return None

    # def get_candles(self, symbol, resolution, start, end):
    #     url = f"{self.base_url}/v2/history/candles"
    #     params = {'symbol': symbol, 'resolution': resolution, 'start': start, 'end': end}

    #     try:
    #         response = requests.get(url, params=params, timeout=(3, 27))  # No headers
    #         response.raise_for_status()
    #         return response.json()
    #     except requests.exceptions.RequestException as e:
    #         print(f"❌ Request error: {e}")
    #         return {"success": False, "error": {"message": str(e)}}

    def get_candles(self, symbol, resolution, start_timestamp, end_timestamp):
        """Fetches historical candles from Delta Exchange.
           Delta's history endpoint expects timestamps in seconds for start/end params.
           The 'time' field in the response might be in seconds or milliseconds, verify.
        """
        path = '/v2/history/candles'
        params = {
            'resolution': resolution,
            'symbol': symbol,
            'start': start_timestamp,
            'end': end_timestamp
        }
        print(f"Attempting to fetch candles from {self.base_url}{path} with params: {params}")

        json_data = self._send_request('GET', path, params=params)

        if json_data and 'result' in json_data and isinstance(json_data['result'], list):
            print(f"\nSuccessfully fetched {len(json_data['result'])} candle data points.")
        else:
            print("\nFailed to fetch candle data or unexpected format.")
        return json_data

    # --- Orders ---
    def get_open_orders(self, symbol=None):
        path = '/v2/orders/open'
        params = {'symbol': symbol} if symbol else {}
        return self._send_request('GET', path, params=params)

    def place_order(self, symbol, side, quantity_in_btc, order_type='market', price=None, stop_price=None, reduce_only=False):
        product_id = self.get_product_id(symbol)
        size_in_lots = int(quantity_in_btc / self.LOT_SIZE_BTC)

        data = {
            'product_id': product_id,
            'side': side,
            'size': size_in_lots,
            'reduce_only': reduce_only
        }

        if order_type == 'market':
            data['order_type'] = 'market_order'
        elif order_type == 'limit':
            data['order_type'] = 'limit_order'
            data['limit_price'] = float(price)
        elif order_type == 'stop':
            data.update({'order_type': 'market_order', 'stop_price': float(stop_price), 'stop_order_type': 'stop_loss_order'})
        elif order_type == 'stop_limit':
            data.update({'order_type': 'limit_order', 'limit_price': float(price), 'stop_price': float(stop_price), 'stop_order_type': 'stop_loss_order'})
        else:
            return {"success": False, "error": {"message": f"Unsupported order_type {order_type}"}}

        return self._send_request('POST', '/v2/orders', data=data)
    
    # --- Candles ---
    def get_candles(self, symbol, resolution, start, end):
        path = '/v2/history/candles'
        params = {'resolution': resolution, 'symbol': symbol, 'start': start, 'end': end}
        return self._send_request('GET', path, params=params)

    # --- Orders ---
    def get_open_orders(self, symbol=None):
        path = '/v2/orders/open'
        params = {'symbol': symbol} if symbol else {}
        return self._send_request('GET', path, params=params)

    def cancel_all_orders(self, product_id=None):
        path = '/v2/orders/all'
        body = {}
        if product_id:
            body['product_id'] = product_id
        return self._send_request('DELETE', path, data=body)

    def cancel_order(self, order_id):
        if not order_id:
            return {"success": False, "error": {"message": "Invalid order_id"}}
        return self._send_request('DELETE', '/v2/orders', data={'order_id': int(order_id)})

    # --- Product ---
    def get_product_details(self, symbol):
        if symbol in self.product_details_cache:
            return self.product_details_cache[symbol]
        response = self._send_request('GET', '/v2/products')
        if response and response.get('success'):
            for product in response['result']:
                if product['symbol'] == symbol:
                    self.product_details_cache[symbol] = product
                    return product
        raise ValueError(f"Product not found: {symbol}")

    def get_product_id(self, symbol):
        return self.get_product_details(symbol)['id']

    # --- Position ---
    def get_position(self, symbol):
        product_id = self.get_product_id(symbol)
        response = self._send_request('GET', '/v2/positions', params={'product_id': product_id})
        if response and response.get('success') and response['result'].get('size', 0) != 0:
            return response['result']
        return None

    # --- Place order ---
    def place_order(self, symbol, side, quantity_in_btc, order_type='market', price=None, stop_price=None, reduce_only=False):
        product_id = self.get_product_id(symbol)
        size_in_lots = int(quantity_in_btc / self.LOT_SIZE_BTC)

        data = {
            'product_id': product_id,
            'side': side,
            'size': size_in_lots,
            'reduce_only': reduce_only
        }

        if order_type == 'market':
            data['order_type'] = 'market_order'
        elif order_type == 'limit':
            data['order_type'] = 'limit_order'
            data['limit_price'] = float(price)
        elif order_type == 'stop':
            data.update({'order_type': 'market_order', 'stop_price': float(stop_price), 'stop_order_type': 'stop_loss_order'})
        elif order_type == 'stop_limit':
            data.update({'order_type': 'limit_order', 'limit_price': float(price), 'stop_price': float(stop_price), 'stop_order_type': 'stop_loss_order'})
        else:
            return {"success": False, "error": {"message": f"Unsupported order_type {order_type}"}}

        return self._send_request('POST', '/v2/orders', data=data)
