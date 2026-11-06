"""
Break of Structure / Change of Character (SMC approximation)
"""
from typing import List
import pandas as pd
from agents.strategies.base import BaseStrategy
from core.models import Signal, Side


class BOSCHOCHStrategy(BaseStrategy):
    name = "BOS_CHOCH"

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.swing = int(self.params.get("swing", 3))
        self.rr = float(self.params.get("rr", 2.2))
        self.atr_sl_mult = float(self.params.get("atr_sl_mult", 1.2))

    def generate(self, df: pd.DataFrame, symbol: str, timeframe: str) -> List[Signal]:
        df = self._ensure_columns(df)
        need = self.swing * 4 + 20
        if len(df) < need:
            return []
        df = df.copy()
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        df["atr"] = tr.rolling(14).mean()

        # Simple swing highs/lows
        highs, lows = [], []
        for i in range(self.swing, len(df) - self.swing):
            w_h = df["high"].iloc[i - self.swing : i + self.swing + 1]
            w_l = df["low"].iloc[i - self.swing : i + self.swing + 1]
            if df["high"].iloc[i] >= w_h.max():
                highs.append((i, float(df["high"].iloc[i])))
            if df["low"].iloc[i] <= w_l.min():
                lows.append((i, float(df["low"].iloc[i])))

        if len(highs) < 2 or len(lows) < 2:
            return []

        last = df.iloc[-1]
        atr = float(last["atr"]) if not pd.isna(last["atr"]) else 0.0
        if atr <= 0:
            return []
        price = float(last["close"])
        signals = []

        # BOS up: close above recent swing high
        sh = highs[-1][1]
        prev_sh = highs[-2][1] if len(highs) >= 2 else sh
        if price > sh and prev_sh < sh:
            entry = price
            sl = entry - atr * self.atr_sl_mult
            risk = entry - sl
            if risk > 0:
                tp = entry + risk * self.rr
                signals.append(Signal(
                    symbol=symbol, side=Side.LONG, entry=entry, sl=sl, tp=tp,
                    confidence=0.70, strategy=self.name,
                    reason=f"BOS up above {sh:.6f}", timeframe=timeframe,
                ))

        # BOS down
        slw = lows[-1][1]
        prev_sl = lows[-2][1] if len(lows) >= 2 else slw
        if price < slw and prev_sl > slw:
            entry = price
            sl = entry + atr * self.atr_sl_mult
            risk = sl - entry
            if risk > 0:
                tp = entry - risk * self.rr
                signals.append(Signal(
                    symbol=symbol, side=Side.SHORT, entry=entry, sl=sl, tp=tp,
                    confidence=0.70, strategy=self.name,
                    reason=f"BOS down below {slw:.6f}", timeframe=timeframe,
                ))

        return signals[:1]
