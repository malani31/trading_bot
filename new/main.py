# your_trading_bot/main.py

import os
import time
import queue
import traceback
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Project imports ---
import config
from api.delta_client import DeltaAPIClient
from ws_confilct.candle_ws import WebSocketCandleClient
from ws_confilct.order_ws import OrderWebSocketRouter
from utils.trade_logger import trade_log, TRADE_LOG_FILE
from utils.indicators import calculate_indicators
from strategy.simple_ema_rsi import (
    check_entry_signal,
    calculate_initial_sl_tp,
    get_initial_historical_candles,
    place_sl_tp_orders,
)
from utils.bot_state_manager import manager as bot_state

# --- REST API client ---
API_KEY = os.getenv("DELTA_API_KEY")
API_SECRET = os.getenv("DELTA_API_SECRET")
if not API_KEY or not API_SECRET:
    raise SystemExit("❌ DELTA_API_KEY / DELTA_API_SECRET not set.")

delta_client = DeltaAPIClient(API_KEY, API_SECRET, config.BASE_URL)

# current_pos = delta_client.get_position(config.SYMBOL)

# if current_pos is not None:
#     size = float(current_pos.get("size", 0.0))
#     avg_price = float(current_pos.get("avg_entry_price", 0.0))

#     # Determine side based on size
#     if size > 0:
#         side = "long"
#     elif size < 0:
#         side = "short"
#     else:
#         side = None

#     if side is not None:
#         bot_state.mark_entry(
#             position_type=side,
#             entry_price=avg_price,
#             position_size=abs(size)
#         )
#         print(f"ℹ️ Existing position detected on startup: {side} {abs(size)} @ {avg_price}")
#     else:
#         bot_state.reset_all()
#         print("ℹ️ No valid open positions on startup, bot is flat")
# else:
#     bot_state.reset_all()
#     print("ℹ️ No open positions on startup, bot is flat")

# --- Safe cancel helper ---
def safe_cancel(client, order_id):
    if not order_id:
        return
    try:
        client.cancel_order(order_id)
    except Exception as e:
        print(f"⚠️ Failed to cancel order {order_id}: {e}")

# --- Main Bot Loop ---
def run_bot():
    print("🤖 Bot starting...")

    candle_queue = queue.Queue()

    # Start WebSocket for candles
    ws_client = WebSocketCandleClient(config.WS_URL, config.SYMBOL, config.RESOLUTION, candle_queue)
    ws_client.start()

    # Start WS router for live order/position updates
    router = OrderWebSocketRouter(
        on_log=lambda m: print(f"[ORDER_WS] {m}"),
        on_error=lambda m: print(f"[ORDER_WS][ERROR] {m}")
    )

    # Make sure enough candles for indicators
    min_candles = max(config.EMA_LONG_PERIOD, config.ATR_PERIOD, config.RSI_PERIOD) + 2
    min_candles = max(min_candles, 50)

    # Seed candles from history
    df_candles = get_initial_historical_candles(config.SYMBOL, config.RESOLUTION, min_candles, delta_client)
    if df_candles.empty:
        print("❌ Initial candle data empty. Exiting.")
        ws_client.stop()
        return

    df_candles = calculate_indicators(df_candles)
    print("✅ Bot ready. Waiting for live candles...")

    while True:
        try:
            new_candle = False
            while not candle_queue.empty():
                c = candle_queue.get(timeout=1)
                cdf = pd.DataFrame([c], index=[c['time']])
                if not df_candles.empty and c['time'] == df_candles.index[-1]:
                    df_candles.loc[c['time']] = cdf.iloc[0]
                else:
                    df_candles = pd.concat([df_candles, cdf])
                df_candles = df_candles.iloc[-(min_candles + 10):]
                new_candle = True

            if not new_candle:
                time.sleep(config.POLLING_INTERVAL_SECONDS)
                continue

            # Recalculate indicators
            df_candles = calculate_indicators(df_candles)
            if pd.isna(df_candles[f'EMA{config.EMA_LONG_PERIOD}'].iloc[-1]) or pd.isna(df_candles['RSI'].iloc[-1]):
                time.sleep(config.POLLING_INTERVAL_SECONDS)
                continue

            current_price = float(df_candles['Close'].iloc[-1])

            # --- POSITION MANAGEMENT ---
            st = bot_state.get_state()
            if st['in_position']:
                # Long position
                if st['current_position_type'] == 'long':
                    if current_price > st['highest_price_since_entry']:
                        new_sl = current_price * (1 - config.TRAIL_STOPLOSS_PCT)
                        # Only update if no previous TSL or new SL is higher
                        if st['trailing_stop_loss_price'] is None or new_sl > st['trailing_stop_loss_price']:
                            print(f"📈 Updating TSL: {st['trailing_stop_loss_price']} → {new_sl:.2f}")
                            safe_cancel(delta_client, st['sl_order_id'])
                            new_sl_id, _ = place_sl_tp_orders(
                                delta_client,
                                config.SYMBOL,
                                'long',
                                new_sl,
                                st['initial_take_profit_price'],
                                st['current_position_size']
                            )
                            if new_sl_id:
                                bot_state.set_sl_tp_order_ids(new_sl_id, st['tp_order_id'])
                            bot_state.set_trailing_stop(new_sl)

                # Short position
                elif st['current_position_type'] == 'short':
                    if current_price < st['lowest_price_since_entry']:
                        new_sl = current_price * (1 + config.TRAIL_STOPLOSS_PCT)
                        # Only update if no previous TSL or new SL is lower
                        if st['trailing_stop_loss_price'] is None or new_sl < st['trailing_stop_loss_price']:
                            print(f"📉 Updating TSL: {st['trailing_stop_loss_price']} → {new_sl:.2f}")
                            safe_cancel(delta_client, st['sl_order_id'])
                            new_sl_id, _ = place_sl_tp_orders(
                                delta_client,
                                config.SYMBOL,
                                'short',
                                new_sl,
                                st['initial_take_profit_price'],
                                st['current_position_size']
                            )
                            if new_sl_id:
                                bot_state.set_sl_tp_order_ids(new_sl_id, st['tp_order_id'])
                            bot_state.set_trailing_stop(new_sl)


            else:
                # --- ENTRY LOGIC (one trade at a time) ---
                entry_signal, signal_type = check_entry_signal(df_candles, st)
                if entry_signal:
                    side = 'buy' if signal_type == 'long' else 'sell'
                    resp = delta_client.place_order(config.SYMBOL, side, config.LOT_SIZE_BTC, order_type='market')
                    if resp and resp.get('success'):
                        avg_price = float(resp['result']['average_fill_price'])
                        print(f"🟢 Entry executed at {avg_price:.2f}")
                        sl, tp = calculate_initial_sl_tp(avg_price, signal_type, config.stoploss_pct, config.target_pct)
                        bot_state.mark_entry(
                            position_type=signal_type,
                            entry_price= avg_price,
                            position_size= config.LOT_SIZE_BTC,
                            sl_price=sl,
                            tp_price=tp
                            )

                        
                        # bot_state.set_initial_sl_tp(sl, tp)

                        sl_id, tp_id = place_sl_tp_orders(delta_client, config.SYMBOL, signal_type, sl, tp, config.LOT_SIZE_BTC)
                        bot_state.set_sl_tp_order_ids(sl_id, tp_id)

            time.sleep(config.POLLING_INTERVAL_SECONDS)

        except queue.Empty:
            pass
        except Exception as e:
            print(f"❌ Loop error: {e}")
            traceback.print_exc()
            time.sleep(config.POLLING_INTERVAL_SECONDS * 5)

# --- EXECUTION ---
if __name__ == "__main__":
    # Ensure trade log exists
    if not os.path.exists(TRADE_LOG_FILE):
        cols = ['Entry Time','Exit Time','Type','Reason','Entry Price','Exit Price','PnL','Net PnL','Session','Initial SL Price','Initial TP Price']
        pd.DataFrame(columns=cols).to_csv(TRADE_LOG_FILE, index=False)
        print(f"Created trade log file: {TRADE_LOG_FILE}")

    try:
        run_bot()
    except KeyboardInterrupt:
        print("🛑 Bot stopped by user.")
    except Exception as e:
        print(f"🔥 Critical error: {e}")
        traceback.print_exc()
