import pandas as pd
import os
from datetime import datetime, timedelta, timezone # Added timezone import
import config # Assuming config.py exists and is relevant

TRADE_LOG_FILE = 'trade_log.csv'

def trade_log(trade_details: dict):
    """
    Logs trade details to a CSV file. If the file does not exist, it creates it
    with a header. If it exists, it appends the new trade without a header.

    Args:
        trade_details (dict): A dictionary containing the details of the trade.
                              Expected keys include 'Type', 'Entry Time',
                              'Exit Time', 'Net PnL', etc.
      (callable): A function (e.g., print, logging.info) to use for
                             logging messages.
    """
    try:
        # Convert the trade details dictionary to a pandas DataFrame.
        # We wrap trade_details in a list to ensure it's treated as a single row.
        df_new_trade = pd.DataFrame([trade_details])

        # Check if the trade log file already exists.
        file_exists = os.path.exists(TRADE_LOG_FILE)

        # Append the new trade to the CSV file.
        # 'mode="a"' ensures append mode.
        # 'header=not file_exists' writes the header only if the file didn't exist.
        # 'index=False' prevents pandas from writing the DataFrame index as a column.
        df_new_trade.to_csv(TRADE_LOG_FILE, mode='a', header=not file_exists, index=False)

        # Log a success message using the provided log_func.
        # Using .get() for dictionary access to prevent KeyError if a key is missing.
        # Formatting Net PnL to two decimal places for readability.
        print(f"📊 Trade logged to {TRADE_LOG_FILE}: "
                 f"Type: {trade_details.get('Type', 'N/A')}, "
                 f"Entry: {trade_details.get('Entry Time', 'N/A')}, "
                 f"Exit: {trade_details.get('Exit Time', 'N/A')}, "
                 f"Net PnL: {trade_details.get('Net PnL', 0.0):.2f}")

    except Exception as e:
        # Log an error message if trade logging fails.
        print(f"❌ Error: Could not log trade to CSV: {e}")

# Example usage (for testing trade_logger.py independently)
if __name__ == "__main__":
    # Ensure a clean start for testing by removing the existing log file if it exists.
    if os.path.exists(TRADE_LOG_FILE):
        os.remove(TRADE_LOG_FILE)
        print(f"Removed existing {TRADE_LOG_FILE} for a clean test run.")

    # Use the built-in 'print' function for logging during independent testing.
    

    print("\n--- Simulating Trades ---")

    # Simulate a long trade.
    # Using datetime.now(timezone.utc) for timezone-aware timestamps.
    trade1 = {
        'Entry Time': datetime.now(timezone.utc) - timedelta(minutes=60),
        'Exit Time': datetime.now(timezone.utc) - timedelta(minutes=30),
        'Type': 'Long',
        'Reason': 'Take Profit',
        'Entry Price': 100000.0,
        'Exit Price': 101000.0,
        'PnL': 1000.0 * 0.001, # Example PnL calculation
        'Net PnL': (1000.0 * 0.001) - 0.10, # Example Net PnL (PnL - commission)
        'Session': 'Europe',
        'Initial SL Price': 99500.0,
        'Initial TP Price': 101000.0
    }
    # Call the trade_log function (corrected name)
    trade_log(trade1)

    # Simulate a short trade.
    trade2 = {
        'Entry Time': datetime.now(timezone.utc) - timedelta(minutes=20),
        'Exit Time': datetime.now(timezone.utc) - timedelta(minutes=10),
        'Type': 'Short',
        'Reason': 'Trailing SL',
        'Entry Price': 101500.0,
        'Exit Price': 101600.0,
        'PnL': -100.0 * 0.001, # Loss for short example
        'Net PnL': (-100.0 * 0.001) - 0.10, # Net PnL (Loss - commission)
        'Session': 'US',
        'Initial SL Price': 102000.0,
        'Initial TP Price': 100500.0
    }
    # Call the trade_log function (corrected name)
    trade_log(trade2)

    # Verify the content of the CSV file after logging.
    print("\n--- Content of trade_log.csv ---")
    try:
        df_logged = pd.read_csv(TRADE_LOG_FILE)
        # Use to_string() to ensure the entire DataFrame is printed, especially for wide tables.
        print(df_logged.to_string())
    except FileNotFoundError:
        print(f"Error: {TRADE_LOG_FILE} not found after logging.")
    except Exception as e:
        print(f"Error reading {TRADE_LOG_FILE}: {e}")
