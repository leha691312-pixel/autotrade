"""
Pivot Scalp - entry off local pivots with ATR stop
"""
from typing import List
import pandas as pd
import numpy as np
from agents.strategies.base import BaseStrategy
from core.models import Signal, Side


class PivotScalpStrategy(BaseStrategy):
    name = "PivotScalp"

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.left = int(self.params.get("left", 2))
        self.right = int(self.params.get("right", 2))
        self.trigger_pct = float(self.params.get("trigger_pct", 0.001))
        self.rr = float(self.params.get("rr", 1.6))

    def generate(self, df: pd.DataFrame, symbol: str, timeframe: str) -> List[Signal]:
        df = self._ensure_columns(df)
        need = self.left + self.right + 5
        if len(df) < need + 20:
            return []

        df = df.copy()
        df["atr"] = self._atr(df)
        i = -(self.right + 1)
        if abs(i) >= len(df):
            return []

        window_h = df["high"].iloc[i - self.left : i + self.right + 1]
        window_l = df["low"].iloc[i - self.left : i + self.right + 1]
        pivot_high = float(df["high"].iloc[i]) >= float(window_h.max()) - 1e-12
        pivot_low = float(df["low"].iloc[i]) <= float(window_l.min()) + 1e-12

        last = df.iloc[-1]
        atr = float(last["atr"]) if not pd.isna(last["atr"]) else 0.0
        if atr <= 0:
            return []

        price = float(last["close"])
        ph = float(df["high"].iloc[i])
        pl = float(df["low"].iloc[i])
        signals = []

        if pivot_low and price > pl * (1 + self.trigger_pct) and last["close"] > last["open"]:
            entry = price
            sl = pl - atr * 0.2
            risk = entry - sl
            if risk > 0:
                tp = entry + risk * self.rr
                signals.append(Signal(
                    symbol=symbol, side=Side.LONG, entry=entry, sl=sl, tp=tp,
                    confidence=0.65, strategy=self.name,
                    reason=f"Pivot LOW long | pivot={pl:.6f}",
                    timeframe=timeframe, extra={"pivot": pl, "type": "pivot_low"},
                ))

        if pivot_high and price < ph * (1 - self.trigger_pct) and last["close"] < last["open"]:
            entry = price
            sl = ph + atr * 0.2
            risk = sl - entry
            if risk > 0:
                tp = entry - risk * self.rr
                signals.append(Signal(
                    symbol=symbol, side=Side.SHORT, entry=entry, sl=sl, tp=tp,
                    confidence=0.65, strategy=self.name,
                    reason=f"Pivot HIGH short | pivot={ph:.6f}",
                    timeframe=timeframe, extra={"pivot": ph, "type": "pivot_high"},
                ))

        return signals[:1]

    def _atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean()
