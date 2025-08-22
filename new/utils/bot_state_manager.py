# # utils/bot_state_manager.py
# import numpy as np
# from datetime import datetime, timezone

# # ---- CENTRALIZED BOT STATE ----
# bot_state = {
#     "in_position": False,
#     "current_position_type": None,   # "long" or "short"
#     "current_position_size": 0.0,
#     "entry_time": None,
#     "entry_price": np.nan,
#     "initial_stop_loss_price": np.nan,
#     "initial_take_profit_price": np.nan,
#     "sl_order_id": None,
#     "tp_order_id": None,
#     "trailing_stop_loss_price": np.nan,
#     "highest_price_since_entry": -np.inf,
#     "lowest_price_since_entry": np.inf,
#     "trade_open_candle_time": None,
#     "current_entry_price": 0.0,
# }

# def reset_bot_state():
#     """Reset to flat after a trade closes."""
#     global bot_state
#     bot_state = {
#         "in_position": False,
#         "current_position_type": None,
#         "current_position_size": 0.0,
#         "entry_time": None,
#         "entry_price": np.nan,
#         "initial_stop_loss_price": np.nan,
#         "initial_take_profit_price": np.nan,
#         "sl_order_id": None,
#         "tp_order_id": None,
#         "trailing_stop_loss_price": np.nan,
#         "highest_price_since_entry": -np.inf,
#         "lowest_price_since_entry": np.inf,
#         "trade_open_candle_time": None,
#         "current_entry_price": 0.0,
#     }
#     print("✅ Bot state has been reset (flat).")

# def set_open_position(side: str, size: float, entry_price: float):
#     """Use this when we (re)discover an open position on the exchange."""
#     bot_state["in_position"] = True
#     bot_state["current_position_type"] = side   # "long" or "short"
#     bot_state["current_position_size"] = abs(size)
#     bot_state["entry_price"] = entry_price
#     bot_state["entry_time"] = datetime.now(timezone.utc)
#     bot_state["current_entry_price"] = entry_price
#     print(f"ℹ️ Synced open position: side={side}, size={size}, entry={entry_price}")

# def set_sl_tp_ids(sl_id: str | None, tp_id: str | None):
#     bot_state["sl_order_id"] = sl_id
#     bot_state["tp_order_id"] = tp_id
# your_trading_bot/state/bot_state_manager.py

from __future__ import annotations

import threading
from dataclasses import dataclass, asdict, field
from typing import Optional, Dict, Any
from datetime import datetime, timezone


@dataclass
class PositionState:
    in_position: bool = False                      # Are we currently in a position?
    current_position_type: Optional[str] = None    # 'long' | 'short' | None
    current_position_size: float = 0.0             # Absolute size (e.g., in BTC)
    current_entry_price: float = 0.0               # Average entry price
    entry_time: Optional[datetime] = None          # When we entered
    trade_open_candle_time: Optional[datetime] = None  # Candle timestamp at entry (optional)

    # Risk management IDs and levels
    sl_order_id: Optional[int] = None
    tp_order_id: Optional[int] = None
    initial_stop_loss_price: Optional[float] = None
    initial_take_profit_price: Optional[float] = None
    trailing_stop_loss_price: Optional[float] = None

    # Running highs/lows (useful for trailing stops)
    highest_price_since_entry: float = float("-inf")
    lowest_price_since_entry: float = float("inf")

    # Last known PnL snapshot (optional; depends on exchange payloads)
    realised_pnl: float = 0.0
    unrealised_pnl: float = 0.0

    # Book-keeping
    last_update_ts: Optional[datetime] = None
    last_exit_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Convert datetimes to ISO for safe UI/logs if needed
        for k in ["entry_time", "trade_open_candle_time", "last_update_ts"]:
            if d.get(k) and isinstance(d[k], datetime):
                d[k] = d[k].astimezone(timezone.utc).isoformat()
        return d


class BotStateManager:
    """
    Thread-safe state manager for your trading bot. This is the single source
    of truth that `simple_ema_rsi.py`, your REST logic, and your WS handlers
    use to stay in sync.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._state = PositionState()

    # -------------------------------
    # Basic accessors
    # -------------------------------
    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            return self._state.to_dict()

    def get_state_object(self) -> PositionState:
        # Use this if you need read-only structured access;
        # do not mutate without holding _lock.
        return self._state

    # -------------------------------
    # Entry / Exit lifecycle
    # -------------------------------
    def mark_entry(
        self,
        position_type: str,
        entry_price: float,
        position_size: float,
        entry_time: Optional[datetime] = None,
        trade_open_candle_time: Optional[datetime] = None,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
    ) -> None:
        if position_type not in ("long", "short"):
            raise ValueError(f"position_type must be 'long' or 'short', got {position_type}")

        with self._lock:
            self._state.in_position = True
            self._state.current_position_type = position_type
            self._state.current_position_size = float(position_size or 0.0)
            self._state.current_entry_price = float(entry_price or 0.0)
            self._state.entry_time = entry_time or datetime.now(timezone.utc)
            self._state.trade_open_candle_time = trade_open_candle_time

            self._state.initial_stop_loss_price = sl_price
            self._state.initial_take_profit_price = tp_price
            self._state.trailing_stop_loss_price = None

            self._state.highest_price_since_entry = float("-inf")
            self._state.lowest_price_since_entry = float("inf")

            self._state.last_exit_reason = None
            self._state.last_update_ts = datetime.now(timezone.utc)

            # Clear old SL/TP IDs; caller can set them later with set_sl_tp_order_ids()
            self._state.sl_order_id = None
            self._state.tp_order_id = None

    def mark_exit(self, exit_reason: str, exit_time: Optional[datetime] = None) -> None:
        with self._lock:
            self._state.in_position = False
            self._state.current_position_type = None
            self._state.current_position_size = 0.0
            self._state.current_entry_price = 0.0
            self._state.entry_time = None
            self._state.trade_open_candle_time = None

            self._state.initial_stop_loss_price = None
            self._state.initial_take_profit_price = None
            self._state.trailing_stop_loss_price = None
            self._state.highest_price_since_entry = float("-inf")
            self._state.lowest_price_since_entry = float("inf")

            self._state.sl_order_id = None
            self._state.tp_order_id = None

            self._state.last_exit_reason = exit_reason
            self._state.last_update_ts = exit_time or datetime.now(timezone.utc)

    def reset_all(self) -> None:
        with self._lock:
            self._state = PositionState()

    # -------------------------------
    # SL/TP helpers
    # -------------------------------
    def set_sl_tp_order_ids(self, sl_order_id: Optional[int], tp_order_id: Optional[int]) -> None:
        with self._lock:
            self._state.sl_order_id = sl_order_id
            self._state.tp_order_id = tp_order_id
            self._state.last_update_ts = datetime.now(timezone.utc)

    def set_trailing_stop(self, price: float) -> None:
        with self._lock:
            self._state.trailing_stop_loss_price = float(price)
            self._state.last_update_ts = datetime.now(timezone.utc)

    # -------------------------------
    # Price extrema (for trailing stops)
    # -------------------------------
    def update_extrema_since_entry(self, last_price: float) -> None:
        with self._lock:
            if not self._state.in_position:
                return

            if last_price is None:
                return

            if self._state.current_position_type == "long":
                if last_price > self._state.highest_price_since_entry:
                    self._state.highest_price_since_entry = last_price
            elif self._state.current_position_type == "short":
                if last_price < self._state.lowest_price_since_entry:
                    self._state.lowest_price_since_entry = last_price

            self._state.last_update_ts = datetime.now(timezone.utc)

    # -------------------------------
    # PnL / position sync (from WS or REST)
    # -------------------------------
    def sync_position_snapshot(
        self,
        current_position_type: Optional[str],
        size: float,
        avg_entry_price: float,
        realised_pnl: Optional[float] = None,
        unrealised_pnl: Optional[float] = None,
    ) -> None:
        """
        Use this to sync from a fresh REST/WS snapshot of your position.
        If size == 0 -> we are flat.
        """
        with self._lock:
            if size and abs(size) > 0:
                self._state.in_position = True
                # If exchange reports side via sign of size, prefer explicit arg
                if current_position_type in ("long", "short"):
                    self._state.current_position_type = current_position_type
                else:
                    # Fallback: positive size -> long, negative -> short
                    self._state.current_position_type = "long" if size > 0 else "short"
            else:
                # Flat
                self._state.in_position = False
                self._state.current_position_type = None

            self._state.current_position_size = abs(float(size or 0.0))
            self._state.current_entry_price = float(avg_entry_price or 0.0)

            if realised_pnl is not None:
                self._state.realised_pnl = float(realised_pnl)
            if unrealised_pnl is not None:
                self._state.unrealised_pnl = float(unrealised_pnl)

            # Keep SL/TP IDs as-is; WS order updates will adjust them
            self._state.last_update_ts = datetime.now(timezone.utc)

    # -------------------------------
    # WS update convenience methods
    # -------------------------------
    def on_order_filled(self, side: str, avg_fill_price: Optional[float], filled_size: float) -> None:
        """
        Called when an order fill message arrives. Use it to detect entries/exits when using
        market/limit orders to open positions (not just SL/TP).
        """
        with self._lock:
            # side is a CLOSE or OPEN intent outside this function;
            # many venues send only 'buy'/'sell'. Strategy logic decides semantics.
            # Here we just update extrema and maybe infer entry/exit if desired.
            if avg_fill_price:
                self.update_extrema_since_entry(avg_fill_price)

            self._state.last_update_ts = datetime.now(timezone.utc)

    def clear_sl_if_order(self, order_id: int) -> None:
        with self._lock:
            if self._state.sl_order_id == order_id:
                self._state.sl_order_id = None
                self._state.last_update_ts = datetime.now(timezone.utc)

    def clear_tp_if_order(self, order_id: int) -> None:
        with self._lock:
            if self._state.tp_order_id == order_id:
                self._state.tp_order_id = None
                self._state.last_update_ts = datetime.now(timezone.utc)


# Export a module-level singleton for convenience across the project
manager = BotStateManager()
