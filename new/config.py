# your_trading_bot/config.py
import os
from dotenv import load_dotenv

# --- Load secrets ---
load_dotenv()  # loads .env file

API_KEY = os.getenv("DELTA_API_KEY")
API_SECRET = os.getenv("DELTA_API_SECRET")

# API_KEY = os.getenv("DELTA_API_KEY")
# API_SECRET = os.getenv("DELTA_API_SECRET")
# --- Base URLs ---
BASE_URL = "https://api.india.delta.exchange"   # live trading REST
# BASE_URL = "https://cdn-ind.testnet.deltaex.org"  # testnet REST

WS_URL = "wss://socket.india.delta.exchange"            # Public WS: price, candles
PRIVATE_WS_URL = "wss://socket.india.delta.exchange/v2" # Private WS: order updates

# --- Trading config ---
SYMBOL = "BTCUSD"
PRODUCT_ID = 27
RESOLUTION = "15m"

# --- Indicators ---
EMA_PERIOD = 25
EMA_LONG_PERIOD=25
ATR_PERIOD = 14
RSI_PERIOD = 14

# --- Strategy params ---
EMA_GAP_THRESHOLD_PCT = 0.001
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
RSI_MOMENTUM_LEVEL = 50

ATR_THRESHOLD_PCT = 0.001
TRAIL_STOPLOSS_PCT = 300  # points

target_pct = 0.005  # 0.5% TP
stoploss_pct = 0.002  # fallback 0.2% SL

USE_CANDLE_SL = True
USE_PCT_SL = False

# --- Lot size ---
DELTA_EXCHANGE_BTC_LOT_SIZE = 0.001  # min lot
LOT_SIZE_BTC = 0.005                 # trading size

assert LOT_SIZE_BTC % DELTA_EXCHANGE_BTC_LOT_SIZE == 0, \
    "LOT_SIZE_BTC must be a multiple of DELTA_EXCHANGE_BTC_LOT_SIZE"

# --- Fees & misc ---
FIXED_FEE_PER_TRADE = float(os.getenv("FEE_PER_TRADE", 0.10))
POLLING_INTERVAL_SECONDS = 50
