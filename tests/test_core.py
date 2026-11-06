"""
Unit tests co ban
Chay: pytest tests/ -v
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pandas as pd
import numpy as np
from datetime import datetime

from core.models import Signal, Side
from agents.risk_gate import RiskGate
from agents.strategies.orb import ORBStrategy


def make_ohlcv(n=100, trend=0.001):
    np.random.seed(42)
    close = 100 * np.cumprod(1 + np.random.randn(n) * 0.01 + trend)
    high = close * (1 + np.abs(np.random.randn(n) * 0.005))
    low = close * (1 - np.abs(np.random.randn(n) * 0.005))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    volume = np.random.uniform(1000, 5000, n)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="15min"),
    })


class TestModels:
    def test_signal_rr(self):
        s = Signal("BTC/USDT", Side.LONG, 100, 95, 110, 0.7, "ORB", "test", "15m")
        assert abs(s.risk_reward() - 2.0) < 1e-6

    def test_signal_to_dict(self):
        s = Signal("ETH/USDT", Side.SHORT, 2000, 2050, 1900, 0.65, "FVG", "reason", "1h")
        d = s.to_dict()
        assert d["side"] == "SHORT"
        assert "rr" in d


class TestRiskGate:
    def test_approve_good_signal(self):
        rg = RiskGate(equity=10000)
        s = Signal("BTC/USDT", Side.LONG, 100, 95, 110, 0.7, "ORB", "test", "15m")
        ok, reason = rg.check(s)
        assert ok is True

    def test_reject_low_rr(self):
        rg = RiskGate(equity=10000)
        s = Signal("BTC/USDT", Side.LONG, 100, 99, 101, 0.7, "ORB", "test", "15m")
        ok, reason = rg.check(s)
        assert ok is False

    def test_kill_switch(self):
        rg = RiskGate(equity=10000)
        rg.activate_kill_switch("TEST")
        s = Signal("BTC/USDT", Side.LONG, 100, 95, 110, 0.7, "ORB", "test", "15m")
        ok, reason = rg.check(s)
        assert ok is False


class TestORB:
    def test_generate_runs(self):
        strat = ORBStrategy()
        df = make_ohlcv(80)
        signals = strat.generate(df, "BTC/USDT:USDT", "15m")
        assert isinstance(signals, list)
