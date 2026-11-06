"""
Fibonacci pullback entry in trend
"""
from typing import List
import pandas as pd
from agents.strategies.base import BaseStrategy
from core.models import Signal, Side


class FibPullbackStrategy(BaseStrategy):
    name = "FibPullback"

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.lookback = int(self.params.get("lookback", 40))
        self.fib_level = float(self.params.get("fib_level", 0.618))
        self.rr = float(self.params.get("rr", 2.0))
        self.tol = float(self.params.get("tol", 0.005))

    def generate(self, df: pd.DataFrame, symbol: str, timeframe: str) -> List[Signal]:
        df = self._ensure_columns(df)
        if len(df) < self.lookback + 5:
            return []
        window = df.iloc[-self.lookback:]
        hi = float(window["high"].max())
        lo = float(window["low"].min())
        if hi <= lo:
            return []
        last = df.iloc[-1]
        price = float(last["close"])
        rng = hi - lo
        fib_long = hi - rng * self.fib_level
        fib_short = lo + rng * self.fib_level

        signals = []
        # Uptrend pullback to fib
        if price > lo + rng * 0.5 and abs(price - fib_long) / price < self.tol and last["close"] > last["open"]:
            entry = price
            sl = lo * 0.998
            risk = entry - sl
            if risk > 0:
                tp = entry + risk * self.rr
                signals.append(Signal(
                    symbol=symbol, side=Side.LONG, entry=entry, sl=sl, tp=tp,
                    confidence=0.67, strategy=self.name,
                    reason=f"Fib {self.fib_level} pullback long", timeframe=timeframe,
                ))
        if price < hi - rng * 0.5 and abs(price - fib_short) / price < self.tol and last["close"] < last["open"]:
            entry = price
            sl = hi * 1.002
            risk = sl - entry
            if risk > 0:
                tp = entry - risk * self.rr
                signals.append(Signal(
                    symbol=symbol, side=Side.SHORT, entry=entry, sl=sl, tp=tp,
                    confidence=0.67, strategy=self.name,
                    reason=f"Fib {self.fib_level} pullback short", timeframe=timeframe,
                ))
        return signals[:1]
