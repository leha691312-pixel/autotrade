"""
Range high/low bounce
"""
from typing import List
import pandas as pd
from agents.strategies.base import BaseStrategy
from core.models import Signal, Side


class RangeBounceStrategy(BaseStrategy):
    name = "RangeBounce"

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.lookback = int(self.params.get("lookback", 30))
        self.rr = float(self.params.get("rr", 1.8))
        self.tol = float(self.params.get("tol", 0.002))

    def generate(self, df: pd.DataFrame, symbol: str, timeframe: str) -> List[Signal]:
        df = self._ensure_columns(df)
        if len(df) < self.lookback + 5:
            return []
        window = df.iloc[-self.lookback:-1]
        hi = float(window["high"].max())
        lo = float(window["low"].min())
        if hi <= lo:
            return []
        last = df.iloc[-1]
        price = float(last["close"])
        mid = (hi + lo) / 2

        signals = []
        if abs(price - lo) / price < self.tol and last["close"] > last["open"]:
            entry = price
            sl = lo * 0.997
            risk = entry - sl
            if risk > 0:
                tp = min(mid, entry + risk * self.rr)
                signals.append(Signal(
                    symbol=symbol, side=Side.LONG, entry=entry, sl=sl, tp=tp,
                    confidence=0.63, strategy=self.name,
                    reason="Range bounce low", timeframe=timeframe,
                ))
        if abs(price - hi) / price < self.tol and last["close"] < last["open"]:
            entry = price
            sl = hi * 1.003
            risk = sl - entry
            if risk > 0:
                tp = max(mid, entry - risk * self.rr)
                signals.append(Signal(
                    symbol=symbol, side=Side.SHORT, entry=entry, sl=sl, tp=tp,
                    confidence=0.63, strategy=self.name,
                    reason="Range bounce high", timeframe=timeframe,
                ))
        return signals[:1]
