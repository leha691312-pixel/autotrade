"""
Risk Gate - bat buoc truoc moi lenh.
Chong lenh trung, position size, RR, daily loss, kill switch.
Theo doi vi the dong (TP/SL) → ghi PnL + huy lenh con lai.
Chi dong som theo TIMEOUT (max hold theo scalp/day/swing).
"""
from datetime import datetime
from typing import Dict, Tuple, Optional, Any, List
from loguru import logger
from core.models import Signal, Side, Position
import yaml
from pathlib import Path


class RiskGate:
    def __init__(self, risk_config: dict = None, equity: float = 10000):
        if risk_config is None:
            with open(Path(__file__).parent.parent / "config" / "risk.yaml") as f:
                risk_config = yaml.safe_load(f)

        self.cfg = risk_config
        self.equity = equity
        self.daily_pnl = 0.0
        self.daily_reset_date = datetime.utcnow().date()
        self.open_positions: Dict[str, Position] = {}
        self.recent_orders: Dict[str, datetime] = {}
        self.consecutive_losses = 0
        self.kill_switch = False
        self.kill_reason = ""
        self.api_errors = 0
        self.api_calls = 0
        self.protective_orders: Dict[str, Dict[str, str]] = {}

        logger.info(
            f"RiskGate initialized | max_open={self.cfg.get('max_open_positions', 10)} | "
            f"invalidation=TIMEOUT only"
        )

    def update_equity(self, equity: float):
        self.equity = equity

    def _reset_daily_if_needed(self):
        today = datetime.utcnow().date()
        if today != self.daily_reset_date:
            self.daily_pnl = 0.0
            self.daily_reset_date = today
            self.consecutive_losses = 0
            logger.info("Daily PnL reset")

    def sync_positions_from_exchange(self, exchange) -> int:
        try:
            positions = exchange.get_positions()
            current: Dict[str, Position] = {}
            for p in positions:
                size = abs(float(p.size or 0))
                if size <= 0:
                    continue
                key = f"{p.symbol}_{p.side.value}"
                old = self.open_positions.get(key)
                if old:
                    p.strategy = getattr(old, "strategy", None) or getattr(p, "strategy", None)
                    if getattr(old, "sl", None):
                        p.sl = old.sl
                    if getattr(old, "tp", None):
                        p.tp = old.tp
                    if getattr(old, "order_id", None):
                        p.order_id = old.order_id
                    if getattr(old, "open_time", None):
                        p.open_time = old.open_time
                    if getattr(old, "timeframe", None):
                        p.timeframe = old.timeframe
                    if getattr(old, "trade_style", None):
                        p.trade_style = old.trade_style
                current[key] = p
            self.open_positions = current
            return len(self.open_positions)
        except Exception as e:
            logger.warning(f"sync_positions_from_exchange: {e}")
            return len(self.open_positions)

    def handle_closed_positions(self, exchange, order_logger=None) -> int:
        closed = 0
        try:
            live = {f"{p.symbol}_{p.side.value}": p for p in exchange.get_positions() if abs(float(p.size or 0)) > 0}
        except Exception:
            live = {}

        to_close = [k for k in list(self.open_positions.keys()) if k not in live]
        for key in to_close:
            pos = self.open_positions.get(key)
            if not pos:
                continue
            pnl = self._estimate_realized_pnl(exchange, pos)
            self.close_position(key, pnl)
            closed += 1
            try:
                exchange.cancel_all_orders(pos.symbol)
            except Exception as e:
                logger.warning(f"Cancel remaining failed {pos.symbol}: {e}")
            if order_logger:
                try:
                    order_logger.log(
                        action="CLOSE",
                        symbol=pos.symbol,
                        side=pos.side.value if hasattr(pos.side, "value") else str(pos.side),
                        size=pos.size,
                        entry=pos.entry_price,
                        pnl=pnl,
                        strategy=getattr(pos, "strategy", ""),
                        status="CLOSED",
                    )
                except Exception:
                    pass
        return closed

    def _estimate_realized_pnl(self, exchange, pos: Position) -> float:
        try:
            ticker = exchange.fetch_ticker(pos.symbol)
            px = float(ticker.get("last") or pos.entry_price)
            if pos.side == Side.LONG or str(pos.side).upper() == "LONG":
                return (px - pos.entry_price) * pos.size
            return (pos.entry_price - px) * pos.size
        except Exception:
            return float(getattr(pos, "unrealized_pnl", 0) or 0)

    def _classify_trade_style(self, strategy: str = "", timeframe: str = "") -> str:
        s = (strategy or "").lower()
        tf = (timeframe or "").lower()
        if any(x in s for x in ("scalp", "pivot", "stoch", "orb", "ema_rsi")):
            return "scalp"
        if any(x in s for x in ("swing", "fib", "bb_squeeze")):
            return "swing"
        if tf in ("1m", "3m", "5m", "15m"):
            return "scalp"
        if tf in ("4h", "1d"):
            return "swing"
        return "day"

    def _timeframe_to_minutes(self, tf: str) -> int:
        m = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
        return m.get((tf or "").lower(), 60)

    def _resolve_max_hold_minutes(self, pos: Position) -> Tuple[int, str]:
        style = getattr(pos, "trade_style", "") or self._classify_trade_style(
            getattr(pos, "strategy", ""), getattr(pos, "timeframe", "")
        )
        defaults = {"scalp": 90, "day": 480, "swing": 2880}
        mins = int(self.cfg.get(f"max_hold_{style}_minutes", defaults.get(style, 480)))
        return mins, style

    def count_positions_by_style(self) -> Dict[str, int]:
        by = {"scalp": 0, "day": 0, "swing": 0}
        for pos in self.open_positions.values():
            style = getattr(pos, "trade_style", "") or self._classify_trade_style(
                getattr(pos, "strategy", ""), getattr(pos, "timeframe", "")
            )
            by[style] = by.get(style, 0) + 1
        return by

    def check_invalidation(self, exchange, pos: Position) -> Tuple[bool, str]:
        max_hold, style = self._resolve_max_hold_minutes(pos)
        open_time = getattr(pos, "open_time", None)
        if open_time:
            age = (datetime.utcnow() - open_time).total_seconds() / 60.0
            if age >= max_hold:
                return True, f"TIMEOUT_{style.upper()}_{int(age)}m"
        return False, ""

    def monitor_invalidations(self, exchange, order_logger=None) -> int:
        n = 0
        for key, pos in list(self.open_positions.items()):
            inv, reason = self.check_invalidation(exchange, pos)
            if inv:
                logger.warning(f"Invalidation {key}: {reason}")
                try:
                    exchange.close_position(pos.symbol, pos.side)
                except Exception as e:
                    logger.error(f"close on invalidation failed: {e}")
                pnl = self._estimate_realized_pnl(exchange, pos)
                self.close_position(key, pnl)
                n += 1
                if order_logger:
                    try:
                        order_logger.log(
                            action="INVALIDATE",
                            symbol=pos.symbol,
                            side=pos.side.value if hasattr(pos.side, "value") else str(pos.side),
                            pnl=pnl,
                            note=reason,
                            status="CLOSED",
                        )
                    except Exception:
                        pass
        return n

    def check(self, signal: Signal, current_price: float = None) -> Tuple[bool, str]:
        self._reset_daily_if_needed()
        if self.kill_switch:
            return False, f"Kill switch: {self.kill_reason}"

        max_open = int(self.cfg.get("max_open_positions", 10))
        if len(self.open_positions) >= max_open:
            return False, f"Max open positions ({max_open})"

        key = f"{signal.symbol}_{signal.side.value}"
        if key in self.open_positions:
            return False, "Already in position"

        cooldown = int(self.cfg.get("symbol_cooldown_seconds", 120))
        last = self.recent_orders.get(signal.symbol)
        if last and (datetime.utcnow() - last).total_seconds() < cooldown:
            return False, "Symbol cooldown"

        min_rr = float(self.cfg.get("min_rr", 1.5))
        rr = signal.risk_reward()
        if rr < min_rr:
            return False, f"RR {rr:.2f} < min {min_rr}"

        max_daily = float(self.cfg.get("max_daily_loss_pct", 0.03))
        if self.equity > 0 and self.daily_pnl / self.equity <= -max_daily:
            self.activate_kill_switch("Daily loss limit")
            return False, "Daily loss limit"

        max_cl = int(self.cfg.get("max_consecutive_losses", 5))
        if self.consecutive_losses >= max_cl:
            self.activate_kill_switch("Consecutive losses")
            return False, "Consecutive losses"

        return True, "OK"

    def register_order(
        self, signal: Signal, order_id: str, size: float,
        sl_order_id: str = "", tp_order_id: str = "",
    ):
        style = self._classify_trade_style(signal.strategy, signal.timeframe)
        pos = Position(
            symbol=signal.symbol,
            side=signal.side,
            entry_price=signal.entry,
            size=size,
            sl=signal.sl,
            tp=signal.tp,
            order_id=order_id,
            strategy=signal.strategy,
            open_time=datetime.utcnow(),
            timeframe=signal.timeframe,
            trade_style=style,
        )
        key = f"{signal.symbol}_{signal.side.value}"
        self.open_positions[key] = pos
        self.recent_orders[signal.symbol] = datetime.utcnow()
        self.protective_orders[key] = {"sl": sl_order_id, "tp": tp_order_id}
        logger.info(f"Registered position {key} size={size} style={style}")

    def close_position(self, key: str, pnl: float):
        self.daily_pnl += pnl
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        self.open_positions.pop(key, None)
        self.protective_orders.pop(key, None)
        logger.info(f"Closed {key} pnl={pnl:.4f} daily={self.daily_pnl:.4f}")

    def activate_kill_switch(self, reason: str):
        self.kill_switch = True
        self.kill_reason = reason
        logger.critical(f"KILL SWITCH: {reason}")

    def reset_kill_switch(self):
        self.kill_switch = False
        self.kill_reason = ""
        logger.info("Kill switch reset")

    def record_api_call(self, success: bool):
        self.api_calls += 1
        if not success:
            self.api_errors += 1
            max_err = int(self.cfg.get("max_api_errors", 20))
            if self.api_errors >= max_err:
                self.activate_kill_switch("API errors")

    def status(self) -> dict:
        by = self.count_positions_by_style()
        return {
            "kill_switch": self.kill_switch,
            "kill_reason": self.kill_reason,
            "daily_pnl": round(self.daily_pnl, 2),
            "open_positions": len(self.open_positions),
            "max_open_positions": int(self.cfg.get("max_open_positions", 10)),
            "positions_by_style": by,
            "consecutive_losses": self.consecutive_losses,
            "equity": self.equity,
        }
