"""
Pullback to EMA in trend
"""
from typing import List
import pandas as pd
from agents.strategies.base import BaseStrategy
from core.models import Signal, Side


class PullbackEMAStrategy(BaseStrategy):
    name = "PullbackEMA"

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.ema_period = int(self.params.get("ema_period", 21))
        self.trend_ema = int(self.params.get("trend_ema", 50))
        self.rr = float(self.params.get("rr", 2.0))
        self.tol = float(self.params.get("tol", 0.003))

    def generate(self, df: pd.DataFrame, symbol: str, timeframe: str) -> List[Signal]:
        df = self._ensure_columns(df)
        if len(df) < self.trend_ema + 5:
            return []
        df = df.copy()
        df["ema"] = df["close"].ewm(span=self.ema_period, adjust=False).mean()
        df["trend"] = df["close"].ewm(span=self.trend_ema, adjust=False).mean()
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        df["atr"] = tr.rolling(14).mean()

        last = df.iloc[-1]
        atr = float(last["atr"]) if not pd.isna(last["atr"]) else 0.0
        if atr <= 0:
            return []

        price = float(last["close"])
        ema = float(last["ema"])
        trend = float(last["trend"])
        dist = abs(price - ema) / price

        signals = []
        if price > trend and dist < self.tol and last["close"] > last["open"]:
            entry = price
            sl = ema - atr * 0.5
            risk = entry - sl
            if risk > 0:
                tp = entry + risk * self.rr
                signals.append(Signal(
                    symbol=symbol, side=Side.LONG, entry=entry, sl=sl, tp=tp,
                    confidence=0.66, strategy=self.name,
                    reason="Pullback EMA long in uptrend", timeframe=timeframe,
                ))
        if price < trend and dist < self.tol and last["close"] < last["open"]:
            entry = price
            sl = ema + atr * 0.5
            risk = sl - entry
            if risk > 0:
                tp = entry - risk * self.rr
                signals.append(Signal(
                    symbol=symbol, side=Side.SHORT, entry=entry, sl=sl, tp=tp,
                    confidence=0.66, strategy=self.name,
                    reason="Pullback EMA short in downtrend", timeframe=timeframe,
                ))
        return signals[:1]
