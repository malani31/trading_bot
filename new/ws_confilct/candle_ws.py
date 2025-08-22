# your_trading_bot/websocket/candle_ws.py

import websocket

import threading
import json
import queue
import pandas as pd # You need pandas for to_datetime
from datetime import datetime, timezone

import time

# IMPORTANT: Adjust this import based on your config file's location.
# If config.py is in the parent directory of 'websocket', use:
import config

# --- WebSocket Client for Real-time Candles ---
class WebSocketCandleClient:
    def __init__(self, ws_url, symbol, resolution, candle_queue: queue.Queue):
        self.ws_url = ws_url
        self.symbol = symbol
        self.resolution = resolution
        self.candle_queue = candle_queue
        self.ws = None
        self.thread = None
        self.running = False

        # --- ADD THESE TWO LINES ---
        self.current_websocket_candle_data = {} # Initialize this dictionary
        self.last_completed_candle_timestamp = None # Initialize this variable
        # ---------------------------

        # Remove these lines as they are redundant with the ones above and cause confusion
        # self.current_websocket_candle = {}
        # self.last_candle_timestamp_processed = None

        self._resolution_seconds = self._get_resolution_seconds(resolution)

    def _get_resolution_seconds(self, res: str) -> int:
        if res.endswith('m'):
            return int(res[:-1]) * 60
        elif res.endswith('h'):
            return int(res[:-1]) * 3600
        elif res.endswith('d'):
            return int(res[:-1]) * 86400
        else:
            raise ValueError(f"Unsupported resolution format: {res}")

    def _send_subscribe_message(self, ws, channel_name, symbols_list):
        payload = {
            "type": "subscribe",
            "payload": {
                "channels": [
                    {
                        "name": channel_name,
                        "symbols": symbols_list
                    }
                ]
            }
        }
        ws.send(json.dumps(payload))
        print(f"Sent subscription message: {json.dumps(payload)}")

    def on_message(self, ws, message):
        try:
            data = json.loads(message)

            if data.get('event') == 'subscribed' or data.get('type') == 'pong' or data.get('type') == 'error':
                if data.get('type') == 'error': print(f"WebSocket Error Message: {data}")
                return

            # Check if this is a candlestick message for the expected resolution
            expected_type = f'candlestick_{self.resolution.replace("m", "").replace("h", "").replace("d", "")}m'
            if data.get('type') != expected_type:
                return # Not a candle message we care about

            candle_start_time_raw = data.get('candle_start_time') # Use candle_start_time from docs
            is_closed = data.get('is_closed', False) # Indicates if the candle is complete

            if candle_start_time_raw is None:
                print(f"Received candle data without 'candle_start_time': {data}. Skipping.")
                return

            try:
                # Based on docs, 'candle_start_time' is in microseconds
                candle_start_dt_utc = pd.to_datetime(candle_start_time_raw, unit='us', utc=True)
            except ValueError as e:
                print(f"Could not parse 'candle_start_time' {candle_start_time_raw}. Error: {e}. Skipping candle.")
                return

            # If this is the first candle data or a new candle interval has started
            if not self.current_websocket_candle_data or candle_start_dt_utc > pd.to_datetime(self.current_websocket_candle_data.get('candle_start_time', 0), unit='us', utc=True):
                # A new candle interval has begun.
                # If we were tracking a previous candle, and it should now be considered complete,
                # then process it and put it into the queue.
                if self.current_websocket_candle_data:
                    # Only queue the previous candle if it was different and not already processed
                    prev_candle_start_dt = pd.to_datetime(self.current_websocket_candle_data['candle_start_time'], unit='us', utc=True)
                    if self.last_completed_candle_timestamp is None or prev_candle_start_dt > self.last_completed_candle_timestamp:
                        # Ensure the previous candle was actually for a full interval
                        # This implicitly handles `is_closed` if the new candle starts
                        # because it means the previous one must have ended.

                        completed_candle = self.current_websocket_candle_data.copy()
                        final_candle = {
                            'time': prev_candle_start_dt, # Use the start time as the candle's index
                            'Open': float(completed_candle.get('open', 0)),
                            'High': float(completed_candle.get('high', 0)),
                            'Low': float(completed_candle.get('low', 0)),
                            'Close': float(completed_candle.get('close', 0)),
                            'Volume': float(completed_candle.get('volume', 0)) # Will be 0 for MARK: symbols
                        }
                        self.candle_queue.put(final_candle)
                        print(f"PUT to queue: Completed candle {final_candle['time']} (due to new candle start)")
                        self.last_completed_candle_timestamp = final_candle['time']

                # Start tracking the new candle
                self.current_websocket_candle_data = data
                print(f"WS: Tracking new candle for {candle_start_dt_utc}")

            # Always update the current in-progress candle with the latest data
            # This handles price updates within the same 15-minute interval
            else:
                self.current_websocket_candle_data.update(data)
                # print(f"WS: Updated in-progress candle for {candle_start_dt_utc} with close {data.get('close')}") # Optional: too verbose

            # If the current candle is explicitly marked as closed by the feed,
            # process it and queue it (if not already queued by new candle start)
            if is_closed:
                current_tracking_start_dt = pd.to_datetime(self.current_websocket_candle_data['candle_start_time'], unit='us', utc=True)
                if self.last_completed_candle_timestamp is None or current_tracking_start_dt > self.last_completed_candle_timestamp:
                    completed_candle = self.current_websocket_candle_data.copy()
                    final_candle = {
                        'time': current_tracking_start_dt,
                        'Open': float(completed_candle.get('open', 0)),
                        'High': float(completed_candle.get('high', 0)),
                        'Low': float(completed_candle.get('low', 0)),
                        'Close': float(completed_candle.get('close', 0)),
                        'Volume': float(completed_candle.get('volume', 0))
                    }
                    self.candle_queue.put(final_candle)
                    print(f"PUT to queue: Completed candle {final_candle['time']} (explicitly closed by feed)")
                    self.last_completed_candle_timestamp = final_candle['time']
                    self.current_websocket_candle_data = {} # Reset as this candle is now closed and processed

        except json.JSONDecodeError as e:
            print(f"WebSocket on_message JSON decoding error: {e}, Message: {message}")
        except KeyError as e:
            print(f"WebSocket on_message KeyError (missing key): {e}, Message: {message}")
        except Exception as e:
            print(f"WebSocket on_message generic error: {e}, Message: {message}")


    def on_error(self, ws, error):
        print(f"WebSocket Error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        print(f"WebSocket Closed: {close_status_code} - {close_msg}")
        if self.running:
            print("Attempting to reconnect WebSocket in 5 seconds...")
            time.sleep(5)
            self.start()

    def on_open(self, ws):
        print(f"WebSocket Opened for {self.symbol} {self.resolution}")
        clean_resolution = self.resolution.replace('m', '').replace('h', '').replace('d', '')
        candle_channel_name = f"candlestick_{clean_resolution}m"
        candle_symbols = [self.symbol]

        self._send_subscribe_message(ws, candle_channel_name, candle_symbols)

    def _run_websocket(self):
        while self.running:
            try:
                self.ws = websocket.WebSocketApp(
                    f"{self.ws_url}",
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                    on_open=self.on_open
                )
                self.ws.run_forever(ping_interval=30, ping_timeout=10, reconnect=5)
            except Exception as e:
                print(f"WebSocket run_forever error: {e}. Retrying in 5 seconds...")
                time.sleep(5)
            if not self.running:
                break
            print("WebSocket run_forever loop exited. Restarting...")


    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run_websocket)
        self.thread.daemon = True
        self.thread.start()
        print("WebSocket client started in a separate thread.")

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()
        if self.thread and self.thread.is_alive():
            print("Waiting for WebSocket thread to stop...")
            self.thread.join(timeout=5)