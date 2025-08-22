# your_trading_bot/strategy/simple_ema_rsi.py

import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from utils.helpers import get_resolution_seconds
from utils.indicators import calculate_indicators
import config
from api.delta_client import DeltaAPIClient


def get_initial_historical_candles(symbol, resolution, min_required_for_indicators, rest_client: DeltaAPIClient):
    """
    Fetches and processes initial historical candles for strategy setup.
    """
    end_datetime_utc = datetime.now(timezone.utc)
    resolution_seconds = get_resolution_seconds(resolution)
    end_datetime_utc = pd.to_datetime(end_datetime_utc).floor(freq=f"{resolution_seconds}s").to_pydatetime()
    end_timestamp_s = int(end_datetime_utc.timestamp())

    # Fetch roughly 2 months of data
    start_datetime_utc = end_datetime_utc - timedelta(days=60)
    start_timestamp_s = int(start_datetime_utc.timestamp())

    print(f"Fetching candles from {start_datetime_utc} to {end_datetime_utc} (UTC).")
    json_data = rest_client.get_candles(symbol, resolution, start_timestamp_s, end_timestamp_s)

    if not json_data or not isinstance(json_data.get("result"), list):
        print("❌ ERROR: API call failed or returned unexpected data format.")
        return pd.DataFrame()

    df_candles = pd.DataFrame(json_data["result"])
    df_candles.columns = df_candles.columns.str.strip()
    df_candles["time"] = pd.to_datetime(df_candles["time"], unit="us", utc=True)
    df_candles.set_index("time", inplace=True)
    df_candles.sort_index(inplace=True)

    df_candles.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        },
        inplace=True,
    )

    # Drop incomplete candle
    last_candle_time = df_candles.index[-1]
    expected_next_candle_start = last_candle_time + timedelta(seconds=resolution_seconds)
    if datetime.now(timezone.utc) < expected_next_candle_start:
        print(f"Dropping incomplete current candle: {last_candle_time}")
        df_candles = df_candles.iloc[:-1]

    # Indicators
    df_candles = calculate_indicators(df_candles)

    # Drop rows with NaN
    required_cols = [f"EMA{config.EMA_PERIOD}", "RSI"]
    initial_rows_before = len(df_candles)
    df_candles.dropna(subset=required_cols, inplace=True)
    rows_dropped = initial_rows_before - len(df_candles)
    if rows_dropped > 0:
        print(f"Dropped {rows_dropped} rows with NaN values.")

    if len(df_candles) < min_required_for_indicators:
        print(f"Not enough candles ({len(df_candles)}/{min_required_for_indicators} required).")
        return pd.DataFrame()

    print(f"✅ Successfully fetched {len(df_candles)} candles with indicators.")
    return df_candles


def check_entry_signal(df_candles_subset, bot_state):
    """
    Check for EMA25 + RSI entry signal.
    Returns (True, 'long') / (True, 'short') or (False, None).
    """
    print("--- Checking Entry Signal ---")
    if bot_state.get("in_position", False):
        print("Already in a position, skipping.")
        return False, None

    if len(df_candles_subset) < 2:
        return False, None

    current = df_candles_subset.iloc[-1]
    prev = df_candles_subset.iloc[-2]

    close = current["Close"]
    ema = current.get(f"EMA{config.EMA_PERIOD}", np.nan)
    rsi = current.get("RSI", np.nan)
    prev_close = prev["Close"]
    prev_ema = prev.get(f"EMA{config.EMA_PERIOD}", np.nan)

    if any(pd.isna([ema, rsi, prev_ema])):
        print("Skipping entry check due to NaN values.")
        return False, None

    # --- Bullish ---
    cond1 = close > ema and prev_close <= prev_ema
    cond2 = rsi > 50
    if cond1 and cond2:
        print(f"✅ LONG Entry Signal at {current.name} | Close {close} > EMA {ema}, RSI {rsi}")
        return True, "long"

    # --- Bearish ---
    cond3 = close < ema and prev_close >= prev_ema
    cond4 = rsi < 50
    if cond3 and cond4:
        print(f"✅ SHORT Entry Signal at {current.name} | Close {close} < EMA {ema}, RSI {rsi}")
        return True, "short"

    print("No entry signal.")
    return False, None


def check_exit_signal(df_candles_subset, bot_state):
    """
    Check for EMA cross or RSI extremes to exit.
    """
    if not bot_state.get("in_position", False) or len(df_candles_subset) < 2:
        return False, None

    current = df_candles_subset.iloc[-1]
    close = current["Close"]
    ema = current.get(f"EMA{config.EMA_PERIOD}", np.nan)
    rsi = current.get("RSI", np.nan)

    if pd.isna(ema) or pd.isna(rsi):
        return False, None

    if bot_state["current_position_type"] == "long":
        if close < ema:
            return True, "Price crossed below EMA"
        if rsi > config.RSI_OVERBOUGHT:
            return True, "RSI overbought"
    elif bot_state["current_position_type"] == "short":
        if close > ema:
            return True, "Price crossed above EMA"
        if rsi < config.RSI_OVERSOLD:
            return True, "RSI oversold"

    return False, None


def place_sl_tp_orders(client: DeltaAPIClient, symbol, position_type, stop_loss_price, take_profit_price, quantity_in_btc):
    """
    Places SL/TP orders.
    """
    sl_order_id = None
    tp_order_id = None
    side = "sell" if position_type == "long" else "buy" if position_type == "short" else None

    if not side:
        print(f"Invalid position type {position_type}")
        return None, None

    print(f"Placing SL at {stop_loss_price}, TP at {take_profit_price}")

    # SL
    try:
        sl_response = client.place_order(
            symbol,
            side,
            quantity_in_btc,
            order_type="stop",
            stop_price=stop_loss_price,
            reduce_only=True,
        )
        if sl_response and sl_response.get("success") and sl_response.get("result", {}).get("id"):
            sl_order_id = int(sl_response["result"]["id"])
            print(f"✅ SL Order ID {sl_order_id}")
    except Exception as e:
        print(f"❌ SL order error: {e}")

    # TP
    try:
        tp_response = client.place_order(
            symbol,
            side,
            quantity_in_btc,
            order_type="limit",
            price=take_profit_price,
            reduce_only=True,
        )
        if tp_response and tp_response.get("success") and tp_response.get("result", {}).get("id"):
            tp_order_id = int(tp_response["result"]["id"])
            print(f"✅ TP Order ID {tp_order_id}")
    except Exception as e:
        print(f"❌ TP order error: {e}")

    return sl_order_id, tp_order_id


def calculate_initial_sl_tp(entry_price, position_type, stoploss_pct, target_pct):
    """
    SL/TP calculation.
    """
    if position_type == "long":
        sl = entry_price * (1 - stoploss_pct)
        tp = entry_price * (1 + target_pct)
    elif position_type == "short":
        sl = entry_price * (1 + stoploss_pct)
        tp = entry_price * (1 - target_pct)
    else:
        print(f"Invalid position type {position_type}")
        return np.nan, np.nan

    return sl, tp
