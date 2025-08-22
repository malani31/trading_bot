# import time
# import json
# import hmac
# import hashlib
# import config
# import threading
# import os
# from dotenv import load_dotenv

# # Load environment variables
# load_dotenv()
# from websocket import WebSocketApp

# from ws_confilct.order_ws import OrderWebSocketRouter
# from utils.bot_state_manager import manager as bot_state

# # -----------------------------
# # 1️⃣ API credentials
# # -----------------------------
# API_KEY = os.getenv("DELTA_API_KEY")
# API_SECRET = os.getenv("DELTA_API_SECRET")
# if not API_KEY or not API_SECRET:
#     raise SystemExit("❌ DELTA_API_KEY / DELTA_API_SECRET not set.")
# def generate_signature(secret: str, message: str) -> str:
#     return hmac.new(
#         bytes(secret, 'utf-8'),
#         bytes(message, 'utf-8'),
#         hashlib.sha256
#     ).hexdigest()

# # -----------------------------
# # 2️⃣ Router for order/position updates
# # -----------------------------
# router = OrderWebSocketRouter(
#     on_log=lambda m: print("[LOG]", m),
#     on_error=lambda m: print("[ERROR]", m),
#     on_event=lambda name, payload: handle_event(name, payload)
# )

# # -----------------------------
# # 3️⃣ Strategy logic
# # -----------------------------
# def handle_event(name, payload):
#     """
#     Called whenever the router detects an order/position update.
#     You can implement your strategy here.
#     """
#     try:
#         if name == "position_update":
#             state = bot_state.get_state()
#             in_position = state.get("in_position", False)
#             current_pos = state.get("current_position_type")
#             print(f"[STRATEGY] In position: {in_position}, Type: {current_pos}")

#             # Example: Only open a new trade if we are flat
#             if not in_position:
#                 # Replace this with your entry logic
#                 print("[STRATEGY] Ready to open a new trade")
#                 # place_order(...) -> implement order placement here
#             else:
#                 print("[STRATEGY] Already in a trade, skipping entry")
#     except Exception as e:
#         print(f"[STRATEGY ERROR] {e}")
# router = OrderWebSocketRouter(
#     on_log=lambda m: print("[LOG]", m),
#     on_error=lambda m: print("[ERROR]", m),
#     on_event=lambda name, payload: handle_event(name, payload)
# )
# # -----------------------------
# # 4️⃣ WebSocket callbacks
# # -----------------------------
# def on_open(ws):
#     timestamp = str(int(time.time()))
#     method = "GET"
#     path = "/live"
#     signature = generate_signature(API_SECRET, method + timestamp + path)

#     # Auth message
#     auth_msg = {
#         "type": "auth",
#         "payload": {
#             "api-key": API_KEY,
#             "signature": signature,
#             "timestamp": timestamp
#         }
#     }
#     ws.send(json.dumps(auth_msg))
#     print("✅ Auth message sent")

#     # Subscribe to private channels
#     ws.send(json.dumps({
#         "type": "subscribe",
#         "payload": {
#             "channels": ["user.orders", "user.positions"]
#         }
#     }))
#     print("✅ Subscription message sent")

# def on_message(ws, message):
#     router.handle_raw_message(message)

# def on_error(ws, error):
#     print("[WS ERROR]", error)

# def on_close(ws, close_status_code, close_msg):
#     print("[WS CLOSED]", close_status_code, close_msg)

# # -----------------------------
# # 5️⃣ Start WebSocket
# # -----------------------------
# def start_ws():
#     print("🔹 WebSocket thread is initializing...")  # <-- add this
#     ws_url = "wss://socket.india.delta.exchange"
#     ws_app = WebSocketApp(
#         ws_url,
#         on_open=on_open,
#         on_message=on_message,
#         on_error=on_error,
#         on_close=on_close
#     )
#     print("🔹 WebSocket connecting to server...")  # <-- add this
#     ws_app.run_forever()

# # ✅ Add this at the very bottom
# if __name__ == "__main__":
#     print("🚀✅  Starting trading bot websocket for order and position open")
#     ws_thread = threading.Thread(target=start_ws, daemon=True)
#     ws_thread.start()
#     print("✅ WebSocket thread started!") 
#     # Main loop for other tasks
#     try:
#         while True:
#             state = bot_state.get_state()
#             print("Current position:", state.get("current_position_type"))
#             print("In position:", state.get("in_position"))
#             time.sleep(10)  # Wait 10 seconds
#     except KeyboardInterrupt:
#         print("🛑 Stopping bot...")

# run_ws.py
import threading
import time
import json
import hmac
import hashlib
import os
from websocket import WebSocketApp
from dotenv import load_dotenv
from ws_confilct.order_ws import OrderWebSocketRouter
from utils.bot_state_manager import manager as bot_state

load_dotenv()

API_KEY = os.getenv("DELTA_API_KEY")
API_SECRET = os.getenv("DELTA_API_SECRET")
if not API_KEY or not API_SECRET:
    raise SystemExit("❌ DELTA_API_KEY / DELTA_API_SECRET not set.")

def generate_signature(secret: str, message: str) -> str:
    return hmac.new(bytes(secret, 'utf-8'), bytes(message, 'utf-8'), hashlib.sha256).hexdigest()

router = OrderWebSocketRouter(
    on_log=lambda m: print("[LOG]", m),
    on_error=lambda m: print("[ERROR]", m),
    on_event=lambda name, payload: print(f"[EVENT] {name}: {payload}")
)

def on_open(ws):
    timestamp = str(int(time.time()))
    method = "GET"
    path = "/live"
    signature = generate_signature(API_SECRET, method + timestamp + path)
    ws.send(json.dumps({"type": "auth", "payload": {"api-key": API_KEY, "signature": signature, "timestamp": timestamp}}))
    print("✅ Auth message sent")
    ws.send(json.dumps({"type": "subscribe", "payload": {"channels": ["user.orders", "user.positions"]}}))
    print("✅ Subscription message sent")

def on_message(ws, message):
    router.handle_raw_message(message)

def on_error(ws, error):
    print("[WS ERROR]", error)

def on_close(ws, close_status_code, close_msg):
    print("[WS CLOSED]", close_status_code, close_msg)

def start_ws():
    print("🔹 WebSocket client starting in a separate thread...")
    ws_url = "wss://socket.india.delta.exchange"
    ws_app = WebSocketApp(ws_url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
    ws_thread = threading.Thread(target=ws_app.run_forever, daemon=True)
    ws_thread.start()
    print("✅ WebSocket thread started!")
    return ws_thread
