# your_trading_bot/ws_confilct/order_ws.py

from __future__ import annotations
from websocket import WebSocketApp
import json
import traceback
from typing import Any, Dict, Optional, Callable
from datetime import datetime, timezone

from utils.bot_state_manager import manager as bot_state


class OrderWebSocketRouter:
    """
    A message router for order/position updates coming from your exchange WebSocket.
    - It does NOT create a WebSocket connection by itself (so no extra deps).
    - Plug its `handle_raw_message(...)` into your existing WS client.
    - It updates the shared bot state via BotStateManager.
    - You can attach optional callbacks for app-level notifications/logging.
    """

    def __init__(
        self,
        on_log: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ):
        """
        on_log(msg):     optional logger (e.g., print or custom logger)
        on_error(msg):   optional error logger
        on_event(name, payload): optional hook for UI/metrics ("order_filled", {...})
        """
        self.on_log = on_log or (lambda m: print(f"[ORDER_WS] {m}"))
        self.on_error = on_error or (lambda m: print(f"[ORDER_WS][ERROR] {m}"))
        self.on_event = on_event or (lambda name, payload: None)

    # ---------------------------------------------------------------------
    # Public entrypoint: call this from your WS client when a message arrives
    # ---------------------------------------------------------------------
    def handle_raw_message(self, raw_message: str) -> None:
        try:
            if not raw_message:
                return
            msg = json.loads(raw_message)
        except Exception:
            self.on_error("Failed to parse JSON from WS message.")
            self.on_error(traceback.format_exc())
            return

        # Delta-like routes often include "type"/"channel"/"event" keys; adapt as needed
        try:
            # Heuristics to detect event type
            if "channel" in msg:
                channel = msg.get("channel", "")
                data = msg.get("data") or msg.get("result") or {}
                if "order" in channel:
                    self._handle_order_update(data)
                elif "position" in channel:
                    self._handle_position_update(data)
                else:
                    # ignore unrelated channels (book/ticker/etc.)
                    pass
            elif "event" in msg:
                # Some WS push style (e.g., {"event": "order_update", "data": {...}})
                event = msg.get("event", "")
                data = msg.get("data", {})
                if event == "order_update":
                    self._handle_order_update(data)
                elif event == "position_update":
                    self._handle_position_update(data)
            else:
                # Fallback: try to infer by presence of typical fields
                if self._looks_like_order(msg):
                    self._handle_order_update(msg)
                elif self._looks_like_position(msg):
                    self._handle_position_update(msg)
        except Exception:
            self.on_error("Unhandled exception while routing WS message.")
            self.on_error(traceback.format_exc())

    # ---------------------------------------------------------------------
    # Order updates
    # ---------------------------------------------------------------------
    def _handle_order_update(self, data: Dict[str, Any]) -> None:
        """
        Normalize common order fields and update state accordingly.
        Expects a dict with fields like:
          id, status, side ('buy'/'sell'), reduce_only, price, avg_fill_price,
          filled_size, remaining_size, stop_price, trigger_status, type ('limit'/'stop'/...)
        """
        # Some servers send arrays of orders
        if isinstance(data, list):
            for item in data:
                self._handle_order_update(item)
            return

        order_id = self._to_int(data.get("id"))
        status = (data.get("status") or data.get("order_state") or "").lower()
        side = (data.get("side") or "").lower()           # 'buy' or 'sell'
        reduce_only = bool(data.get("reduce_only")) or bool(data.get("reduceOnly"))
        order_type = (data.get("type") or data.get("order_type") or "").lower()
        avg_fill_price = self._to_float(data.get("avg_fill_price") or data.get("avg_fill") or data.get("average_price"))
        filled_size = self._to_float(data.get("filled_size") or data.get("filled_qty") or data.get("filled")) or 0.0
        remaining_size = self._to_float(data.get("remaining_size") or data.get("remaining_qty") or data.get("unfilled")) or 0.0
        price = self._to_float(data.get("price"))
        stop_price = self._to_float(data.get("stop_price") or data.get("trigger_price"))

        self.on_log(
            f"Order Update: id={order_id} status={status} side={side} reduce_only={reduce_only} "
            f"type={order_type} filled={filled_size} remaining={remaining_size} price={price} stop={stop_price}"
        )

        # Inform app hooks
        self.on_event("order_update", data)

        # Update SL/TP IDs if these are reduce-only orders we placed
        if order_id and reduce_only:
            # Heuristic: a stop reduce-only is SL, a limit reduce-only is TP
            if order_type == "stop":
                # If it filled/canceled/expired -> clear
                if status in ("filled", "cancelled", "canceled", "rejected", "expired"):
                    bot_state.clear_sl_if_order(order_id)
                else:
                    # Register SL order ID (active)
                    current = bot_state.get_state()
                    if current.get("sl_order_id") != order_id:
                        bot_state.set_sl_tp_order_ids(order_id, current.get("tp_order_id"))
            elif order_type == "limit":
                if status in ("filled", "cancelled", "canceled", "rejected", "expired"):
                    bot_state.clear_tp_if_order(order_id)
                else:
                    current = bot_state.get_state()
                    if current.get("tp_order_id") != order_id:
                        bot_state.set_sl_tp_order_ids(current.get("sl_order_id"), order_id)

        # If order filled, let state know (useful analytics)
        if status in ("filled", "partially_filled"):
            bot_state.on_order_filled(side=side, avg_fill_price=avg_fill_price, filled_size=filled_size)

        # Optional: If this is an opening order (reduce_only==False) and status==filled,
        # you could infer mark_entry/mark_exit here; typically you'd do this using
        # position updates instead to avoid edge cases.

    # ---------------------------------------------------------------------
    # Position updates
    # ---------------------------------------------------------------------
    def _handle_position_update(self, data: Dict[str, Any]) -> None:
        """
        Normalize common position fields and reconcile bot state.
        Expected keys (varies by venue):
          size, entry_price, side ('buy'/'sell' or direction)
          realised_pnl, unrealised_pnl, avg_entry_price
        """
        # Some servers send arrays of positions
        if isinstance(data, list):
            for item in data:
                self._handle_position_update(item)
            return

        size = self._to_float(
            data.get("size")
            or data.get("position_size")
            or data.get("quantity")
            or 0.0
        )
        # Average entry price
        aep = self._to_float(
            data.get("avg_entry_price")
            or data.get("average_entry_price")
            or data.get("entry_price")
            or 0.0
        )

        side_raw = (data.get("side") or data.get("direction") or "").lower()  # 'buy'/'sell' or 'long'/'short'
        direction = self._normalize_direction(side_raw, size)

        realised_pnl = self._to_float(data.get("realised_pnl") or data.get("realized_pnl"))
        unrealised_pnl = self._to_float(data.get("unrealised_pnl") or data.get("unrealized_pnl"))

        self.on_log(
            f"Position Update: size={size} direction={direction} avg_entry={aep} "
            f"realised={realised_pnl} unrealised={unrealised_pnl}"
        )

        self.on_event("position_update", data)

        # Sync shared bot state (this is the robust way to stay aligned with the exchange)
        bot_state.sync_position_snapshot(
            current_position_type=direction,
            size=size,
            avg_entry_price=aep,
            realised_pnl=realised_pnl,
            unrealised_pnl=unrealised_pnl,
        )

        # If now flat, ensure SL/TP IDs are cleared (exchange may auto-cancel on close)
        if not size or abs(size) == 0:
            st = bot_state.get_state()
            if st.get("sl_order_id") or st.get("tp_order_id"):
                bot_state.set_sl_tp_order_ids(None, None)

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------
    def _looks_like_order(self, msg: Dict[str, Any]) -> bool:
        return any(k in msg for k in ("order", "order_id", "avg_fill_price", "order_state", "stop_price", "reduce_only", "filled_size"))

    def _looks_like_position(self, msg: Dict[str, Any]) -> bool:
        return any(k in msg for k in ("position", "size", "avg_entry_price", "entry_price", "unrealised_pnl", "unrealized_pnl"))

    @staticmethod
    def _to_int(v: Any) -> Optional[int]:
        try:
            if v is None:
                return None
            return int(v)
        except Exception:
            return None

    @staticmethod
    def _to_float(v: Any) -> Optional[float]:
        try:
            if v is None or v == "":
                return None
            return float(v)
        except Exception:
            return None

    @staticmethod
    def _normalize_direction(side: str, size: Optional[float]) -> Optional[str]:
        """
        Convert various 'side' encodings to 'long' or 'short'.
        If side ambiguous, infer from sign of size (if provided).
        """
        if side in ("long", "buy"):
            return "long"
        if side in ("short", "sell"):
            return "short"
        if size is not None:
            if size > 0:
                return "long"
            if size < 0:
                return "short"
        return None


# ------------------------------
# Example glue (optional)
# ------------------------------
# If your WS client gives you messages via a callback:
#
#   router = OrderWebSocketRouter(on_log=my_logger, on_error=my_err, on_event=my_event)
#
#   def on_message_from_ws(raw_str: str):
#       router.handle_raw_message(raw_str)
#
#   ws_client.on_message = on_message_from_ws
#
# Your trading loop / strategy can then read state like:
#   from state.bot_state_manager import manager as bot_state
#   st = bot_state.get_state()
#   if not st["in_position"]:
#       ...
