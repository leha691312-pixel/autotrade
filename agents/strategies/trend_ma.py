"""
Trend following with dual MA
"""
from typing import List
import pandas as pd
from agents.strategies.base import BaseStrategy
from core.models import Signal, Side


class TrendMAStrategy(BaseStrategy):
    name = "TrendMA"

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.fast = int(self.params.get("ema_fast", 9))
        self.slow = int(self.params.get("ema_slow", 21))
        self.rr = float(self.params.get("rr", 2.0))
        self.atr_sl_mult = float(self.params.get("atr_sl_mult", 1.5))

    def generate(self, df: pd.DataFrame, symbol: str, timeframe: str) -> List[Signal]:
        df = self._ensure_columns(df)
        if len(df) < self.slow + 10:
            return []
        df = df.copy()
        df["ema_f"] = df["close"].ewm(span=self.fast, adjust=False).mean()
        df["ema_s"] = df["close"].ewm(span=self.slow, adjust=False).mean()
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        df["atr"] = tr.rolling(14).mean()

        last = df.iloc[-1]
        prev = df.iloc[-2]
        atr = float(last["atr"]) if not pd.isna(last["atr"]) else 0.0
        if atr <= 0:
            return []

        cross_up = prev["ema_f"] <= prev["ema_s"] and last["ema_f"] > last["ema_s"]
        cross_dn = prev["ema_f"] >= prev["ema_s"] and last["ema_f"] < last["ema_s"]

        signals = []
        if cross_up:
            entry = float(last["close"])
            sl = entry - atr * self.atr_sl_mult
            risk = entry - sl
            if risk > 0:
                tp = entry + risk * self.rr
                signals.append(Signal(
                    symbol=symbol, side=Side.LONG, entry=entry, sl=sl, tp=tp,
                    confidence=0.65, strategy=self.name,
                    reason=f"Trend MA cross UP {self.fast}/{self.slow}", timeframe=timeframe,
                ))
        if cross_dn:
            entry = float(last["close"])
            sl = entry + atr * self.atr_sl_mult
            risk = sl - entry
            if risk > 0:
                tp = entry - risk * self.rr
                signals.append(Signal(
                    symbol=symbol, side=Side.SHORT, entry=entry, sl=sl, tp=tp,
                    confidence=0.65, strategy=self.name,
                    reason=f"Trend MA cross DOWN {self.fast}/{self.slow}", timeframe=timeframe,
                ))
        return signals[:1]
