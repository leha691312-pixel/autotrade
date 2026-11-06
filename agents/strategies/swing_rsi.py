"""
Swing RSI mean reversion / momentum
"""
from typing import List
import pandas as pd
from agents.strategies.base import BaseStrategy
from core.models import Signal, Side


class SwingRSIStrategy(BaseStrategy):
    name = "SwingRSI"

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.rsi_period = int(self.params.get("rsi_period", 14))
        self.oversold = float(self.params.get("oversold", 30))
        self.overbought = float(self.params.get("overbought", 70))
        self.rr = float(self.params.get("rr", 2.0))
        self.atr_sl_mult = float(self.params.get("atr_sl_mult", 1.5))

    def generate(self, df: pd.DataFrame, symbol: str, timeframe: str) -> List[Signal]:
        df = self._ensure_columns(df)
        if len(df) < self.rsi_period + 15:
            return []
        df = df.copy()
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(self.rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(self.rsi_period).mean()
        rs = gain / loss.replace(0, float("nan"))
        df["rsi"] = 100 - (100 / (1 + rs))
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        df["atr"] = tr.rolling(14).mean()

        last = df.iloc[-1]
        prev = df.iloc[-2]
        atr = float(last["atr"]) if not pd.isna(last["atr"]) else 0.0
        rsi = float(last["rsi"]) if not pd.isna(last["rsi"]) else 50.0
        if atr <= 0:
            return []

        signals = []
        if prev["rsi"] < self.oversold <= rsi:
            entry = float(last["close"])
            sl = entry - atr * self.atr_sl_mult
            risk = entry - sl
            if risk > 0:
                tp = entry + risk * self.rr
                signals.append(Signal(
                    symbol=symbol, side=Side.LONG, entry=entry, sl=sl, tp=tp,
                    confidence=0.66, strategy=self.name,
                    reason=f"Swing RSI exit oversold {rsi:.1f}", timeframe=timeframe,
                ))
        if prev["rsi"] > self.overbought >= rsi:
            entry = float(last["close"])
            sl = entry + atr * self.atr_sl_mult
            risk = sl - entry
            if risk > 0:
                tp = entry - risk * self.rr
                signals.append(Signal(
                    symbol=symbol, side=Side.SHORT, entry=entry, sl=sl, tp=tp,
                    confidence=0.66, strategy=self.name,
                    reason=f"Swing RSI exit overbought {rsi:.1f}", timeframe=timeframe,
                ))
        return signals[:1]
