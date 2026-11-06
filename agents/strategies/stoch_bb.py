"""
Stochastic + Bollinger Band mean reversion scalp
"""
from typing import List
import pandas as pd
import numpy as np
from agents.strategies.base import BaseStrategy
from core.models import Signal, Side


class StochBBStrategy(BaseStrategy):
    name = "StochBB"

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.k_period = int(self.params.get("k_period", 5))
        self.d_period = int(self.params.get("d_period", 3))
        self.bb_period = int(self.params.get("bb_period", 13))
        self.bb_std = float(self.params.get("bb_std", 3.0))
        self.rr = float(self.params.get("rr", 1.6))

    def generate(self, df: pd.DataFrame, symbol: str, timeframe: str) -> List[Signal]:
        df = self._ensure_columns(df)
        if len(df) < max(self.k_period, self.bb_period) + 10:
            return []
        df = df.copy()
        low_min = df["low"].rolling(self.k_period).min()
        high_max = df["high"].rolling(self.k_period).max()
        df["stoch_k"] = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
        df["stoch_d"] = df["stoch_k"].rolling(self.d_period).mean()
        mid = df["close"].rolling(self.bb_period).mean()
        std = df["close"].rolling(self.bb_period).std()
        df["bb_upper"] = mid + self.bb_std * std
        df["bb_lower"] = mid - self.bb_std * std
        df["bb_mid"] = mid

        last = df.iloc[-1]
        prev = df.iloc[-2]
        if pd.isna(last["stoch_k"]) or pd.isna(last["bb_lower"]):
            return []

        signals = []
        # Oversold bounce
        if last["close"] <= last["bb_lower"] and last["stoch_k"] < 20 and prev["stoch_k"] <= last["stoch_k"]:
            entry = float(last["close"])
            sl = entry * 0.995
            risk = entry - sl
            if risk > 0:
                tp = min(float(last["bb_mid"]), entry + risk * self.rr)
                signals.append(Signal(
                    symbol=symbol, side=Side.LONG, entry=entry, sl=sl, tp=tp,
                    confidence=0.64, strategy=self.name,
                    reason=f"StochBB oversold K={last['stoch_k']:.1f}", timeframe=timeframe,
                ))
        # Overbought fade
        if last["close"] >= last["bb_upper"] and last["stoch_k"] > 80 and prev["stoch_k"] >= last["stoch_k"]:
            entry = float(last["close"])
            sl = entry * 1.005
            risk = sl - entry
            if risk > 0:
                tp = max(float(last["bb_mid"]), entry - risk * self.rr)
                signals.append(Signal(
                    symbol=symbol, side=Side.SHORT, entry=entry, sl=sl, tp=tp,
                    confidence=0.64, strategy=self.name,
                    reason=f"StochBB overbought K={last['stoch_k']:.1f}", timeframe=timeframe,
                ))
        return signals[:1]
