# utils/indicators.py

import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
import config  # Assuming config.py is in the parent directory

def calculate_indicators(df_candles: pd.DataFrame):
    """Calculates EMA25, ATR, and RSI for the DataFrame."""
    if df_candles.empty:
        return df_candles

    # Ensure OHLCV columns are numeric
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        df_candles[col] = pd.to_numeric(df_candles[col], errors='coerce')

    df_candles.sort_index(inplace=True)

    # ✅ EMA25
    df_candles[f'EMA{config.EMA_PERIOD}'] = (
        df_candles['Close'].ewm(span=config.EMA_PERIOD, adjust=False).mean()
    )

    # ✅ ATR
    if len(df_candles) >= config.ATR_PERIOD:
        df_candles['TR'] = np.maximum(
            df_candles['High'] - df_candles['Low'],
            np.abs(df_candles['High'] - df_candles['Close'].shift(1)),
            np.abs(df_candles['Low'] - df_candles['Close'].shift(1))
        )
        df_candles['ATR'] = df_candles['TR'].rolling(
            window=config.ATR_PERIOD, min_periods=config.ATR_PERIOD
        ).mean()
    else:
        df_candles['TR'] = np.nan
        df_candles['ATR'] = np.nan

    # ✅ RSI
    if len(df_candles) >= config.RSI_PERIOD:
        df_candles['RSI'] = RSIIndicator(
            close=df_candles['Close'], window=config.RSI_PERIOD, fillna=False
        ).rsi()
    else:
        df_candles['RSI'] = np.nan

    return df_candles
