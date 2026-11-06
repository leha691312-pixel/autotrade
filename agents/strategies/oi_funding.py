"""
Open Interest + Funding rate confluence
"""
from typing import List, Optional
import pandas as pd
from agents.strategies.base import BaseStrategy
from core.models import Signal, Side


class OIFundingStrategy(BaseStrategy):
    name = "OI_Funding"

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.rr = float(self.params.get("rr", 2.0))
        self.funding_threshold = float(self.params.get("funding_threshold", 0.0003))
        self.atr_sl_mult = float(self.params.get("atr_sl_mult", 1.5))

    def generate(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        oi_series: Optional[pd.Series] = None,
        funding_rate: Optional[float] = None,
    ) -> List[Signal]:
        df = self._ensure_columns(df)
        if len(df) < 30:
            return []

        df = df.copy()
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        df["atr"] = tr.rolling(14).mean()
        df["ema"] = df["close"].ewm(span=21, adjust=False).mean()

        last = df.iloc[-1]
        atr = float(last["atr"]) if not pd.isna(last["atr"]) else 0.0
        if atr <= 0:
            return []

        fr = float(funding_rate or 0)
        oi_up = False
        if oi_series is not None and len(oi_series) >= 2:
            try:
                oi_up = float(oi_series.iloc[-1]) > float(oi_series.iloc[0])
            except Exception:
                oi_up = False

        signals = []
        # Positive funding extreme + price below EMA → short squeeze risk → long bias careful
        # Rising OI + price up + negative funding → long continuation
        if oi_up and fr < -self.funding_threshold and last["close"] > last["ema"]:
            entry = float(last["close"])
            sl = entry - atr * self.atr_sl_mult
            risk = entry - sl
            if risk > 0:
                tp = entry + risk * self.rr
                signals.append(Signal(
                    symbol=symbol, side=Side.LONG, entry=entry, sl=sl, tp=tp,
                    confidence=0.62, strategy=self.name,
                    reason=f"OI up + neg funding {fr:.5f}", timeframe=timeframe,
                ))
        if oi_up and fr > self.funding_threshold and last["close"] < last["ema"]:
            entry = float(last["close"])
            sl = entry + atr * self.atr_sl_mult
            risk = sl - entry
            if risk > 0:
                tp = entry - risk * self.rr
                signals.append(Signal(
                    symbol=symbol, side=Side.SHORT, entry=entry, sl=sl, tp=tp,
                    confidence=0.62, strategy=self.name,
                    reason=f"OI up + pos funding {fr:.5f}", timeframe=timeframe,
                ))
        return signals[:1]
