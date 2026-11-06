"""
Fair Value Gap fill / continuation
"""
from typing import List
import pandas as pd
from agents.strategies.base import BaseStrategy
from core.models import Signal, Side


class FVGStrategy(BaseStrategy):
    name = "FVG"

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.lookback = int(self.params.get("lookback", 30))
        self.rr = float(self.params.get("rr", 2.0))
        self.min_gap_pct = float(self.params.get("min_gap_pct", 0.002))

    def generate(self, df: pd.DataFrame, symbol: str, timeframe: str) -> List[Signal]:
        df = self._ensure_columns(df)
        if len(df) < self.lookback + 5:
            return []

        signals = []
        last = df.iloc[-1]
        for i in range(len(df) - self.lookback, len(df) - 2):
            if i < 1:
                continue
            c0 = df.iloc[i - 1]
            c1 = df.iloc[i]
            c2 = df.iloc[i + 1]
            # Bullish FVG: gap between c0 high and c2 low
            if c2["low"] > c0["high"]:
                gap = (c2["low"] - c0["high"]) / c0["high"]
                if gap >= self.min_gap_pct:
                    if c0["high"] <= last["low"] <= c2["low"] or c0["high"] <= last["close"] <= c2["low"]:
                        entry = float(last["close"])
                        sl = float(c0["high"]) * 0.997
                        risk = entry - sl
                        if risk > 0:
                            tp = entry + risk * self.rr
                            signals.append(Signal(
                                symbol=symbol, side=Side.LONG, entry=entry, sl=sl, tp=tp,
                                confidence=0.68, strategy=self.name,
                                reason="Bullish FVG retest", timeframe=timeframe,
                            ))
                            break
            # Bearish FVG
            if c2["high"] < c0["low"]:
                gap = (c0["low"] - c2["high"]) / c0["low"]
                if gap >= self.min_gap_pct:
                    if c2["high"] <= last["high"] <= c0["low"] or c2["high"] <= last["close"] <= c0["low"]:
                        entry = float(last["close"])
                        sl = float(c0["low"]) * 1.003
                        risk = sl - entry
                        if risk > 0:
                            tp = entry - risk * self.rr
                            signals.append(Signal(
                                symbol=symbol, side=Side.SHORT, entry=entry, sl=sl, tp=tp,
                                confidence=0.68, strategy=self.name,
                                reason="Bearish FVG retest", timeframe=timeframe,
                            ))
                            break
        return signals[:1]
