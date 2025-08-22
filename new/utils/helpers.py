# your_trading_bot/utils/helpers.py

from datetime import datetime, timezone
import pytz

def get_session(timestamp):
    """Determines the trading session based on UTC hour."""
    hour = timestamp.hour
    if 0 <= hour < 8:
        return 'Asia'
    elif 8 <= hour < 16:
        return 'Europe'
    else:
        return 'US'

def get_resolution_seconds(resolution_str):
    """Converts resolution string to seconds."""
    if resolution_str.endswith('m'):
        return int(resolution_str[:-1]) * 60
    elif resolution_str.endswith('h'):
        return int(resolution_str[:-1]) * 3600 # Corrected 'res' to 'resolution_str'
    elif resolution_str.endswith('d'): # Corrected 'res' to 'resolution_str'
        return int(resolution_str[:-1]) * 86400
    return 0
