"""
Bollinger Band Squeeze breakout
"""
from typing import List
import pandas as pd
import numpy as np
from agents.strategies.base import BaseStrategy
from core.models import Signal, Side


class BBSqueezeStrategy(BaseStrategy):
    name = "BBSqueeze"

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.bb_period = int(self.params.get("bb_period", 20))
        self.bb_std = float(self.params.get("bb_std", 2.0))
        self.kc_period = int(self.params.get("kc_period", 20))
        self.kc_atr_mult = float(self.params.get("kc_atr_mult", 1.5))
        self.rr = float(self.params.get("rr", 2.0))

    def generate(self, df: pd.DataFrame, symbol: str, timeframe: str) -> List[Signal]:
        df = self._ensure_columns(df)
        if len(df) < self.bb_period + 10:
            return []
        df = df.copy()
        mid = df["close"].rolling(self.bb_period).mean()
        std = df["close"].rolling(self.bb_period).std()
        df["bb_upper"] = mid + self.bb_std * std
        df["bb_lower"] = mid - self.bb_std * std
        df["bb_mid"] = mid
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(self.kc_period).mean()
        kc_mid = df["close"].rolling(self.kc_period).mean()
        df["kc_upper"] = kc_mid + self.kc_atr_mult * atr
        df["kc_lower"] = kc_mid - self.kc_atr_mult * atr
        df["squeeze"] = (df["bb_lower"] > df["kc_lower"]) & (df["bb_upper"] < df["kc_upper"])

        last = df.iloc[-1]
        prev = df.iloc[-2]
        if pd.isna(last["bb_upper"]):
            return []

        signals = []
        # Squeeze release + breakout
        was_squeeze = bool(prev["squeeze"]) if not pd.isna(prev["squeeze"]) else False
        now_squeeze = bool(last["squeeze"]) if not pd.isna(last["squeeze"]) else False
        if was_squeeze and not now_squeeze:
            if last["close"] > last["bb_upper"]:
                entry = float(last["close"])
                sl = float(last["bb_mid"])
                risk = entry - sl
                if risk > 0:
                    tp = entry + risk * self.rr
                    signals.append(Signal(
                        symbol=symbol, side=Side.LONG, entry=entry, sl=sl, tp=tp,
                        confidence=0.68, strategy=self.name,
                        reason="BB Squeeze release UP", timeframe=timeframe,
                    ))
            elif last["close"] < last["bb_lower"]:
                entry = float(last["close"])
                sl = float(last["bb_mid"])
                risk = sl - entry
                if risk > 0:
                    tp = entry - risk * self.rr
                    signals.append(Signal(
                        symbol=symbol, side=Side.SHORT, entry=entry, sl=sl, tp=tp,
                        confidence=0.68, strategy=self.name,
                        reason="BB Squeeze release DOWN", timeframe=timeframe,
                    ))
        return signals[:1]
