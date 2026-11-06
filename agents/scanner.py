"""
Market Scanner Agent - quet Top N coin + chay strategy duoc bat
Toi uu: parallel fetch OHLCV / funding / OI (ThreadPoolExecutor)
"""
from typing import List, Optional, Dict, Any, Tuple
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import time as _time
import pandas as pd
from loguru import logger
from core.exchange import ExchangeWrapper
from agents.strategies import get_all_strategies, list_strategy_names
from core.models import Signal


class ScannerAgent:
    def __init__(
        self,
        exchange: ExchangeWrapper,
        top_n: int = 20,
        timeframes: List[str] = None,
        enabled_strategies: Optional[List[str]] = None,
        strategy_params: Optional[Dict[str, dict]] = None,
        excluded_symbols: Optional[List[str]] = None,
        max_workers: int = 12,
        ohlcv_limit: int = 150,
    ):
        self.exchange = exchange
        self.top_n = top_n
        self.timeframes = timeframes or ["15m", "1h"]
        self.enabled_strategies = enabled_strategies
        self.strategy_params = strategy_params or {}
        self.strategies = get_all_strategies(
            enabled=enabled_strategies,
            strategy_params=strategy_params,
        )
        self.last_dfs: Dict[str, pd.DataFrame] = {}
        self.excluded_symbols: set = set()
        self.set_excluded_symbols(excluded_symbols or [])
        self.max_workers = max(2, min(int(max_workers), 24))
        self.ohlcv_limit = max(60, int(ohlcv_limit))
        names = [s.name for s in self.strategies]
        logger.info(
            f"ScannerAgent ready | Top {top_n} | TFs={self.timeframes} | "
            f"workers={self.max_workers} limit={self.ohlcv_limit} | "
            f"Excluded={len(self.excluded_symbols)} | "
            f"Strategies ({len(names)}): {names}"
        )

    @staticmethod
    def normalize_symbol(sym: str, quote: str = "USDT") -> str:
        if not sym:
            return ""
        s = str(sym).strip().upper().replace(" ", "")
        if not s:
            return ""
        if f":{quote}" in s:
            return s
        if s.endswith(f"/{quote}"):
            return f"{s}:{quote}"
        if s.endswith(quote) and "/" not in s:
            base = s[: -len(quote)]
            if base:
                return f"{base}/{quote}:{quote}"
        if "/" in s and ":" not in s:
            return f"{s}:{quote}"
        if "/" not in s and ":" not in s:
            return f"{s}/{quote}:{quote}"
        return s

    def set_excluded_symbols(self, symbols) -> int:
        out = set()
        for x in symbols or []:
            n = self.normalize_symbol(str(x))
            if n:
                out.add(n)
                base = n.split("/")[0]
                if base:
                    out.add(base)
        self.excluded_symbols = out
        return len([s for s in out if "/" in s])

    def is_excluded(self, symbol: str) -> bool:
        if not self.excluded_symbols:
            return False
        n = self.normalize_symbol(symbol)
        if n in self.excluded_symbols:
            return True
        base = (n.split("/")[0] if n else "").upper()
        if base and base in self.excluded_symbols:
            return True
        if str(symbol).strip().upper() in self.excluded_symbols:
            return True
        return False

    def excluded_list_display(self) -> list:
        return sorted(s for s in self.excluded_symbols if "/" in s)

    def reload_strategies(
        self,
        enabled: Optional[List[str]] = None,
        strategy_params: Optional[Dict[str, dict]] = None,
    ):
        if enabled is not None:
            self.enabled_strategies = enabled
        if strategy_params is not None:
            self.strategy_params = strategy_params
        self.strategies = get_all_strategies(
            enabled=self.enabled_strategies,
            strategy_params=self.strategy_params,
        )
        logger.info(f"Strategies reloaded: {[s.name for s in self.strategies]}")

    def _need_oi_funding(self) -> bool:
        return any(s.name == "OI_Funding" for s in self.strategies)

    def _fetch_ohlcv_one(self, symbol: str, tf: str) -> Tuple[str, str, Optional[pd.DataFrame]]:
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, tf, limit=self.ohlcv_limit)
            if not ohlcv or len(ohlcv) < 50:
                return symbol, tf, None
            df = pd.DataFrame(
                ohlcv,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            return symbol, tf, df
        except Exception as e:
            logger.debug(f"ohlcv {symbol} {tf}: {e}")
            return symbol, tf, None

    def _fetch_meta_one(self, symbol: str) -> Tuple[str, Optional[float], Optional[float]]:
        funding_rate = None
        oi_value = None
        try:
            fr = self.exchange.fetch_funding_rate(symbol)
            if fr and "fundingRate" in fr:
                funding_rate = float(fr["fundingRate"])
        except Exception:
            pass
        try:
            oi = self.exchange.fetch_open_interest(symbol)
            if oi and "openInterestAmount" in oi:
                oi_value = float(oi["openInterestAmount"])
            elif oi and "openInterest" in oi:
                oi_value = float(oi["openInterest"])
        except Exception:
            pass
        return symbol, funding_rate, oi_value

    def scan(self) -> List[Signal]:
        t0 = _time.time()

        symbols = self.exchange.get_top_symbols(self.top_n)
        if self.excluded_symbols:
            before = len(symbols)
            symbols = [s for s in symbols if not self.is_excluded(s)]
            skipped = before - len(symbols)
            if skipped:
                logger.info(f"Excluded {skipped} symbol(s) from scan blacklist")

        logger.info(
            f"Scanning {len(symbols)} symbols | strategies={[s.name for s in self.strategies]} "
            f"| TFs={self.timeframes} workers={self.max_workers} blacklist={len(self.excluded_list_display())}"
        )

        all_signals: List[Signal] = []
        per_strat: Counter = Counter()
        self.last_dfs = {}

        # parallel OHLCV
        jobs = [(sym, tf) for sym in symbols for tf in self.timeframes]
        ohlcv_map: Dict[Tuple[str, str], pd.DataFrame] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futs = [pool.submit(self._fetch_ohlcv_one, sym, tf) for sym, tf in jobs]
            for fut in as_completed(futs):
                try:
                    sym, tf, df = fut.result()
                    if df is not None:
                        ohlcv_map[(sym, tf)] = df
                        self.last_dfs[sym] = df
                        self.last_dfs[f"{sym}_{tf}"] = df
                except Exception as e:
                    logger.debug(f"ohlcv worker: {e}")

        t_ohlcv = _time.time()

        # funding/OI only if OI_Funding enabled
        meta: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
        if self._need_oi_funding() and symbols:
            with ThreadPoolExecutor(max_workers=min(8, self.max_workers)) as pool:
                futs = [pool.submit(self._fetch_meta_one, sym) for sym in symbols]
                for fut in as_completed(futs):
                    try:
                        sym, fr, oi = fut.result()
                        meta[sym] = (fr, oi)
                    except Exception:
                        pass
        t_meta = _time.time()

        for symbol in symbols:
            funding_rate, oi_value = meta.get(symbol, (None, None))
            for tf in self.timeframes:
                df = ohlcv_map.get((symbol, tf))
                if df is None or len(df) < 50:
                    continue
                for strat in self.strategies:
                    try:
                        if strat.name == "OI_Funding":
                            oi_series = None
                            if oi_value is not None:
                                oi_series = pd.Series(
                                    [oi_value * 0.97] * (len(df) - 1) + [oi_value]
                                )
                            signals = strat.generate(
                                df, symbol, tf,
                                oi_series=oi_series,
                                funding_rate=funding_rate,
                            )
                        else:
                            signals = strat.generate(df, symbol, tf)
                        if signals:
                            if not isinstance(signals, list):
                                signals = [signals]
                            signals = [x for x in signals if x is not None]
                            all_signals.extend(signals)
                            per_strat[strat.name] += len(signals)
                    except Exception as e:
                        logger.debug(f"Strategy {strat.name} error {symbol} {tf}: {e}")

        all_signals.sort(key=lambda sig: getattr(sig, "confidence", 0) or 0, reverse=True)
        elapsed = _time.time() - t0

        if per_strat:
            detail = ", ".join(f"{k}={v}" for k, v in sorted(per_strat.items(), key=lambda x: -x[1]))
            logger.info(
                f"Found {len(all_signals)} raw signals | by strategy: {detail} | "
                f"scan={elapsed:.1f}s (ohlcv={t_ohlcv-t0:.1f}s meta={t_meta-t_ohlcv:.1f}s strat={elapsed-(t_meta-t0):.1f}s)"
            )
        else:
            logger.info(f"Found 0 raw signals | scan={elapsed:.1f}s")

        return all_signals

    @staticmethod
    def available_strategies() -> List[str]:
        return list_strategy_names()
