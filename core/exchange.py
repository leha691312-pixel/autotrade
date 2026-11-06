"""
Exchange wrapper: paper / testnet / live
Testnet+Live: REST truc tiep + ccxt (tranh margin/sapi loi tren testnet)
SL/TP: uu tien Algo Order API (STOP_MARKET / TAKE_PROFIT_MARKET)
"""
import os, time, uuid, hmac, hashlib, math, urllib.parse
from typing import Dict, List, Optional, Any
from datetime import datetime
import requests
import ccxt
from loguru import logger
from core.models import Mode, Side, Position, OrderStatus

TESTNET_BASE = "https://testnet.binancefuture.com"
LIVE_BASE = "https://fapi.binance.com"


class ExchangeWrapper:
    def __init__(self, mode: str = "paper", config: dict = None):
        self.mode = Mode(mode)
        self.config = config or {}
        self.exchange = None
        self.base = LIVE_BASE
        self.api_key = ""
        self.api_secret = ""
        self.paper_balance = float(self.config.get("initial_capital", 10000))
        self.paper_positions: Dict[str, Position] = {}
        self.paper_orders: Dict[str, dict] = {}
        self.paper_trades: List[dict] = []
        self.markets: Dict[str, Any] = {}
        self._id_to_unified: Dict[str, str] = {}
        self._unified_to_id: Dict[str, str] = {}
        self._init_exchange()

    def _init_exchange(self):
        if self.mode == Mode.PAPER:
            logger.info("Exchange mode: PAPER")
            return
        options = {"defaultType": "future", "adjustForTimeDifference": True, "recvWindow": 60000, "fetchCurrencies": False}
        if self.mode == Mode.TESTNET:
            self.base = TESTNET_BASE
            self.api_key = os.getenv("BINANCE_TESTNET_API_KEY", "") or os.getenv("BINANCE_DEMO_API_KEY", "")
            self.api_secret = os.getenv("BINANCE_TESTNET_API_SECRET", "") or os.getenv("BINANCE_DEMO_API_SECRET", "")
            self.exchange = ccxt.binanceusdm({"apiKey": self.api_key, "secret": self.api_secret, "options": options, "enableRateLimit": True})
            self.exchange.urls["api"] = {
                "fapiPublic": self.base + "/fapi/v1", "fapiPublicV2": self.base + "/fapi/v2",
                "fapiPublicV3": self.base + "/fapi/v3", "fapiPrivate": self.base + "/fapi/v1",
                "fapiPrivateV2": self.base + "/fapi/v2", "fapiPrivateV3": self.base + "/fapi/v3",
                "public": self.base + "/fapi/v1", "private": self.base + "/fapi/v1",
            }
            logger.info(f"Exchange mode: TESTNET REST {self.base}")
        else:
            self.base = LIVE_BASE
            self.api_key = os.getenv("BINANCE_API_KEY", "")
            self.api_secret = os.getenv("BINANCE_API_SECRET", "")
            self.exchange = ccxt.binanceusdm({"apiKey": self.api_key, "secret": self.api_secret, "options": options, "enableRateLimit": True})
            logger.warning("Exchange mode: LIVE")
        self.load_markets()

    def load_markets(self):
        if self.mode == Mode.PAPER:
            return
        try:
            r = requests.get(f"{self.base}/fapi/v1/exchangeInfo", timeout=15)
            r.raise_for_status()
            data = r.json()
            markets = {}
            for s in data.get("symbols") or []:
                if s.get("contractType") != "PERPETUAL":
                    continue
                if s.get("status") not in ("TRADING", "LIVE"):
                    continue
                base_a, quote_a = s.get("baseAsset"), s.get("quoteAsset")
                if not base_a or not quote_a:
                    continue
                market_id = s.get("symbol") or f"{base_a}{quote_a}"
                unified = f"{base_a}/{quote_a}:{quote_a}"
                filters = {f["filterType"]: f for f in (s.get("filters") or []) if f.get("filterType")}
                lot = filters.get("LOT_SIZE") or filters.get("MARKET_LOT_SIZE") or {}
                price_f = filters.get("PRICE_FILTER") or {}
                markets[unified] = {
                    "id": market_id, "symbol": unified, "base": base_a, "quote": quote_a,
                    "settle": quote_a, "active": True, "spot": False, "swap": True, "future": True,
                    "expiry": None, "info": s,
                    "precision": {
                        "amount": self._precision_from_filter(lot, "stepSize"),
                        "price": self._precision_from_filter(price_f, "tickSize"),
                    },
                    "limits": {
                        "amount": {"min": self._float_filter(lot, "minQty"), "max": self._float_filter(lot, "maxQty")},
                        "cost": {"min": self._float_filter(filters.get("MIN_NOTIONAL") or {}, "notional")},
                    },
                }
                self._id_to_unified[market_id] = unified
                self._unified_to_id[unified] = market_id
            self.markets = markets
            if self.exchange is not None:
                self.exchange.markets = markets
                self.exchange.markets_by_id = {v["id"]: v for v in markets.values()}
            logger.info(f"Loaded {len(markets)} perpetual markets from {self.base}")
        except Exception as e:
            logger.error(f"load_markets failed: {e}")
            try:
                if self.exchange:
                    self.exchange.load_markets()
                    self.markets = self.exchange.markets or {}
            except Exception as e2:
                logger.error(f"ccxt load_markets failed: {e2}")

    @staticmethod
    def _precision_from_filter(f: dict, key: str) -> int:
        try:
            step = str(f.get(key) or "0.001")
            if "." in step:
                return len(step.rstrip("0").split(".")[-1])
            return 0
        except Exception:
            return 3

    @staticmethod
    def _float_filter(f: dict, key: str) -> Optional[float]:
        try:
            v = f.get(key)
            return float(v) if v is not None else None
        except Exception:
            return None

    def _raw_sym(self, symbol: str) -> str:
        if "/" not in symbol:
            return symbol
        if symbol in self._unified_to_id:
            return self._unified_to_id[symbol]
        return symbol.replace("/", "").replace(":USDT", "").replace(":USDC", "")

    def _sym(self, symbol: str) -> str:
        if "/" in symbol:
            return symbol
        if symbol in self._id_to_unified:
            return self._id_to_unified[symbol]
        if symbol.endswith("USDT"):
            return f"{symbol[:-4]}/USDT:USDT"
        return symbol

    def _market_id(self, symbol: str) -> str:
        return self._raw_sym(symbol)

    def _filters(self, symbol: str) -> dict:
        raw = self._raw_sym(symbol)
        m = None
        if self.markets:
            for k, v in self.markets.items():
                if v.get("id") == raw or k == raw:
                    m = v
                    break
            if m is None:
                uni = self._id_to_unified.get(raw)
                if uni:
                    m = self.markets.get(uni)
        step, tick, min_qty, max_qty, min_notional = 0.001, 0.0001, 0.0, 1e12, 5.0
        if m:
            info = m.get("info") or {}
            for f in info.get("filters") or []:
                ft = f.get("filterType")
                if ft == "LOT_SIZE":
                    step = float(f.get("stepSize") or step)
                    min_qty = float(f.get("minQty") or 0)
                    mq = float(f.get("maxQty") or 0)
                    if mq > 0:
                        max_qty = min(max_qty, mq)
                elif ft == "MARKET_LOT_SIZE":
                    step_m = float(f.get("stepSize") or step)
                    if step_m > 0:
                        step = step_m
                    mq = float(f.get("maxQty") or 0)
                    if mq > 0:
                        max_qty = min(max_qty, mq)
                elif ft == "PRICE_FILTER":
                    tick = float(f.get("tickSize") or tick)
                elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
                    min_notional = float(f.get("notional") or f.get("minNotional") or min_notional)
            lim = m.get("limits") or {}
            if lim.get("amount", {}).get("min") is not None:
                min_qty = float(lim["amount"]["min"])
            if lim.get("cost", {}).get("min") is not None:
                min_notional = float(lim["cost"]["min"])
        return {"step": step, "tick": tick, "min_qty": min_qty, "max_qty": max_qty, "min_notional": min_notional}

    @staticmethod
    def _round_step(value: float, step: float) -> float:
        if step <= 0:
            return value
        precision = max(0, int(round(-math.log10(step)))) if step < 1 else 0
        rounded = math.floor(value / step + 1e-12) * step
        return float(f"{rounded:.{precision}f}")

    def round_qty(self, symbol: str, qty: float) -> float:
        f = self._filters(symbol)
        q = self._round_step(qty, f["step"])
        if q < f["min_qty"]:
            return 0.0
        return min(q, f["max_qty"])

    def round_price(self, symbol: str, price: float) -> float:
        return self._round_step(price, self._filters(symbol)["tick"])

    def _server_time_ms(self) -> int:
        try:
            r = requests.get(f"{self.base}/fapi/v1/time", timeout=5)
            return int(r.json()["serverTime"])
        except Exception:
            return int(time.time() * 1000)

    def _signed_request(self, method: str, path: str, params: dict = None) -> Any:
        params = dict(params or {})
        params["timestamp"] = self._server_time_ms()
        params["recvWindow"] = 60000
        query = urllib.parse.urlencode(params)
        sig = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        url = f"{self.base}{path}?{query}&signature={sig}"
        headers = {"X-MBX-APIKEY": self.api_key}
        r = requests.request(method, url, headers=headers, timeout=15)
        if r.status_code >= 400:
            raise Exception(f"REST {method} {path}: {r.status_code} {r.text[:300]}")
        return r.json() if r.text else {}

    def _fapi(self, path: str, method: str = "GET", params: dict = None):
        if self.mode == Mode.PAPER:
            return None
        try:
            return self._signed_request(method, path if path.startswith("/") else f"/fapi/v1/{path}", params)
        except Exception as e:
            logger.debug(f"fapi {method} {path}: {e}")
            return None

    def fetch_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 500) -> List[list]:
        if self.mode == Mode.PAPER:
            public = ccxt.binanceusdm({"enableRateLimit": True, "options": {"defaultType": "future"}})
            return public.fetch_ohlcv(symbol, timeframe, limit=limit)
        try:
            raw = self._raw_sym(symbol)
            r = requests.get(f"{self.base}/fapi/v1/klines", params={"symbol": raw, "interval": timeframe, "limit": limit}, timeout=15)
            r.raise_for_status()
            return [[int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])] for x in r.json()]
        except Exception as e:
            logger.warning(f"fetch_ohlcv REST fail {symbol}: {e}")
            if self.exchange:
                return self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            raise

    def fetch_ticker(self, symbol: str) -> dict:
        if self.mode == Mode.PAPER:
            public = ccxt.binanceusdm({"enableRateLimit": True, "options": {"defaultType": "future"}})
            return public.fetch_ticker(symbol)
        try:
            raw = self._raw_sym(symbol)
            r = requests.get(f"{self.base}/fapi/v1/ticker/24hr", params={"symbol": raw}, timeout=10)
            r.raise_for_status()
            d = r.json()
            return {"symbol": symbol, "last": float(d.get("lastPrice") or 0), "bid": float(d.get("bidPrice") or 0),
                    "ask": float(d.get("askPrice") or 0), "quoteVolume": float(d.get("quoteVolume") or 0), "info": d}
        except Exception:
            if self.exchange:
                return self.exchange.fetch_ticker(symbol)
            raise

    def fetch_order_book(self, symbol: str, limit: int = 20) -> dict:
        if self.mode == Mode.PAPER:
            public = ccxt.binanceusdm({"enableRateLimit": True, "options": {"defaultType": "future"}})
            return public.fetch_order_book(symbol, limit)
        try:
            r = requests.get(f"{self.base}/fapi/v1/depth", params={"symbol": self._raw_sym(symbol), "limit": limit}, timeout=10)
            r.raise_for_status()
            d = r.json()
            return {"bids": [[float(p), float(q)] for p, q in d.get("bids", [])], "asks": [[float(p), float(q)] for p, q in d.get("asks", [])]}
        except Exception:
            if self.exchange:
                return self.exchange.fetch_order_book(symbol, limit)
            raise

    def fetch_funding_rate(self, symbol: str) -> dict:
        try:
            r = requests.get(f"{self.base}/fapi/v1/premiumIndex", params={"symbol": self._raw_sym(symbol)}, timeout=10)
            r.raise_for_status()
            d = r.json()
            return {"symbol": symbol, "fundingRate": float(d.get("lastFundingRate") or 0), "info": d}
        except Exception:
            return {}

    def fetch_open_interest(self, symbol: str) -> dict:
        try:
            r = requests.get(f"{self.base}/fapi/v1/openInterest", params={"symbol": self._raw_sym(symbol)}, timeout=10)
            r.raise_for_status()
            d = r.json()
            return {"symbol": symbol, "openInterestAmount": float(d.get("openInterest") or 0), "info": d}
        except Exception:
            return {}

    def _is_tradable_market(self, market: dict, quote: str = "USDT") -> bool:
        if not market or not market.get("active", True) or market.get("spot"):
            return False
        if market.get("expiry") or market.get("expiryDatetime"):
            return False
        info = market.get("info") or {}
        status = str(info.get("status") or info.get("contractStatus") or "").upper()
        if status and status not in ("TRADING", "LIVE"):
            return False
        symbol = market.get("symbol") or ""
        return f"/{quote}" in symbol or f":{quote}" in symbol

    def _normalize_symbol(self, sym: str, quote: str = "USDT") -> str:
        if not sym:
            return sym
        if f":{quote}" in sym:
            return sym
        if sym.endswith(f"/{quote}"):
            return f"{sym}:{quote}"
        return sym

    def get_top_symbols(self, n: int = 20, quote: str = "USDT") -> List[str]:
        default_pairs = ["BTC/USDT:USDT", "ETH/USDT:USDT", "BNB/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT"]
        markets = self.markets or {}
        if not markets and self.mode != Mode.PAPER:
            self.load_markets()
            markets = self.markets or {}
        if not markets and self.mode == Mode.PAPER:
            try:
                public = ccxt.binanceusdm({"enableRateLimit": True, "options": {"defaultType": "future"}})
                public.load_markets()
                markets = public.markets or {}
            except Exception:
                return default_pairs[:n]
        tradable = set()
        for sym, m in markets.items():
            try:
                if self._is_tradable_market(m, quote):
                    tradable.add(self._normalize_symbol(sym, quote))
            except Exception:
                continue
        tickers = {}
        try:
            r = requests.get(f"{self.base}/fapi/v1/ticker/24hr", timeout=15)
            r.raise_for_status()
            for d in r.json():
                mid = d.get("symbol") or ""
                uni = self._id_to_unified.get(mid) or self._normalize_symbol(mid, quote)
                tickers[uni] = {"quoteVolume": float(d.get("quoteVolume") or 0)}
        except Exception as e:
            logger.warning(f"fetch tickers: {e}")
        ranked = []
        for sym, t in tickers.items():
            norm = self._normalize_symbol(sym, quote)
            if tradable and norm not in tradable:
                continue
            vol = float(t.get("quoteVolume") or 0)
            if vol > 0:
                ranked.append((norm, vol))
        ranked.sort(key=lambda x: x[1], reverse=True)
        result, seen = [], set()
        for s, _ in ranked:
            if s not in seen:
                seen.add(s)
                result.append(s)
            if len(result) >= n:
                break
        if not result:
            result = default_pairs[:n]
        logger.info(f"Top symbols ({self.mode.value}): {len(result)}/{n}")
        return result[:n]

    def get_balance(self) -> float:
        if self.mode == Mode.PAPER:
            return self.paper_balance
        try:
            data = self._signed_request("GET", "/fapi/v2/balance")
            for item in data or []:
                if item.get("asset") == "USDT":
                    return float(item.get("availableBalance") or item.get("balance") or 0)
        except Exception as e:
            logger.warning(f"get_balance REST: {e}")
            if self.exchange:
                bal = self.exchange.fetch_balance()
                return float(bal.get("USDT", {}).get("free", 0))
        return 0.0

    def get_positions(self) -> List[Position]:
        if self.mode == Mode.PAPER:
            return list(self.paper_positions.values())
        positions = []
        try:
            raw = self._signed_request("GET", "/fapi/v2/positionRisk")
            for p in raw or []:
                amt = float(p.get("positionAmt") or 0)
                if abs(amt) <= 0:
                    continue
                side = Side.LONG if amt > 0 else Side.SHORT
                mid = p.get("symbol") or ""
                symbol = self._id_to_unified.get(mid) or self._sym(mid)
                positions.append(Position(
                    symbol=symbol, side=side, entry_price=float(p.get("entryPrice") or 0),
                    size=abs(amt), sl=0.0, tp=0.0, order_id="", strategy="unknown",
                    open_time=datetime.utcnow(), leverage=int(float(p.get("leverage") or 1)),
                    unrealized_pnl=float(p.get("unRealizedProfit") or 0),
                ))
        except Exception as e:
            logger.warning(f"get_positions: {e}")
        return positions

    def create_order(self, symbol: str, side: str, amount: float, price: Optional[float] = None,
                     order_type: str = "market", params: dict = None) -> dict:
        params = params or {}
        amount = self.round_qty(symbol, amount)
        if amount <= 0:
            raise ValueError(f"Invalid amount after rounding for {symbol}")
        if price is not None:
            price = self.round_price(symbol, price)
        if self.mode == Mode.PAPER:
            return self._paper_create_order(symbol, side, amount, price, order_type, params)
        ot = (order_type or "market").upper()
        if ot in ("STOP_MARKET", "TAKE_PROFIT_MARKET", "STOP", "TAKE_PROFIT"):
            return self._create_algo_order(symbol, side, amount, price, ot, params)
        try:
            if self.exchange:
                return self.exchange.create_order(symbol=symbol, type=order_type, side=side, amount=amount, price=price, params=params)
            raise Exception("no exchange")
        except Exception as e:
            logger.error(f"Order failed: {e}")
            raise

    def _create_algo_order(self, symbol: str, side: str, amount: float, price, order_type: str, params: dict) -> dict:
        stop_price = params.get("stopPrice") or price
        if stop_price is None:
            raise ValueError("stopPrice required for algo order")
        stop_price = self.round_price(symbol, float(stop_price))
        amount = self.round_qty(symbol, amount)
        mid = self._market_id(symbol)
        algo_type = "STOP_MARKET" if "STOP" in order_type.upper() else "TAKE_PROFIT_MARKET"
        body = {
            "algoType": "CONDITIONAL", "symbol": mid, "side": side.upper(),
            "type": algo_type, "triggerPrice": stop_price, "quantity": amount,
            "reduceOnly": "true" if params.get("reduceOnly", True) else "false",
            "workingType": params.get("workingType") or "CONTRACT_PRICE",
            "clientAlgoId": f"bot{uuid.uuid4().hex[:16]}",
        }
        if params.get("closePosition"):
            body["closePosition"] = "true"
            body.pop("quantity", None)
        data = self._signed_request("POST", "/fapi/v1/algoOrder", body)
        logger.info(f"Algo {algo_type} {symbol} {side} qty={amount} trigger={stop_price}")
        return {"id": str(data.get("algoId") or data.get("clientAlgoId") or ""), "symbol": symbol,
                "side": side, "amount": amount, "price": stop_price, "stopPrice": stop_price,
                "type": algo_type, "status": "open", "info": data}

    def _paper_create_order(self, symbol, side, amount, price, order_type, params):
        order_id = str(uuid.uuid4())[:12]
        ot = (order_type or "market").upper()
        params = params or {}
        if ot in ("STOP_MARKET", "TAKE_PROFIT_MARKET", "STOP", "TAKE_PROFIT"):
            stop_price = params.get("stopPrice") or price
            order = {"id": order_id, "symbol": symbol, "side": side, "amount": amount, "price": stop_price,
                     "stopPrice": stop_price, "type": ot, "status": "open", "timestamp": int(time.time() * 1000),
                     "info": {"paper": True, "reduceOnly": params.get("reduceOnly", True)}}
            self.paper_orders[order_id] = order
            return order
        ticker = self.fetch_ticker(symbol)
        fill_price = price or ticker["last"]
        slip = 0.0002
        fill_price *= (1 + slip) if side == "buy" else (1 - slip)
        order = {"id": order_id, "symbol": symbol, "side": side, "amount": amount, "price": fill_price,
                 "type": ot, "status": "closed", "timestamp": int(time.time() * 1000), "info": {"paper": True}}
        self.paper_orders[order_id] = order
        return order

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        if self.mode == Mode.PAPER:
            return True
        try:
            self._signed_request("POST", "/fapi/v1/leverage", {"symbol": self._market_id(symbol), "leverage": int(leverage)})
            return True
        except Exception as e:
            logger.warning(f"set_leverage {symbol}: {e}")
            return False

    def set_margin_mode(self, symbol: str, mode: str = "isolated") -> bool:
        if self.mode == Mode.PAPER:
            return True
        mode = (mode or "isolated").upper()
        if mode not in ("ISOLATED", "CROSSED"):
            mode = "ISOLATED"
        try:
            self._signed_request("POST", "/fapi/v1/marginType", {"symbol": self._market_id(symbol), "marginType": mode})
            return True
        except Exception as e:
            err = str(e).lower()
            if "no need to change" in err or "already" in err:
                return True
            logger.warning(f"set_margin_mode {symbol}: {e}")
            return False

    def prepare_symbol(self, symbol: str, leverage: int) -> bool:
        return self.set_margin_mode(symbol, "isolated") and self.set_leverage(symbol, leverage)

    def _algo_id_to_ccxt_symbol(self, market_id: str) -> str:
        return self._id_to_unified.get(market_id) or self._sym(market_id)

    def _cancel_algo_conditional(self, symbol: str) -> int:
        mid = self._market_id(symbol)
        n = 0
        algos = self._fapi("/fapi/v1/openAlgoOrders", "GET", {"symbol": mid}) or self._fapi("/fapi/v1/openAlgoOrders", "GET", {})
        if isinstance(algos, dict):
            algos = algos.get("orders") or algos.get("data") or []
        for a in algos or []:
            try:
                a_sym = str(a.get("symbol") or "")
                if a_sym and a_sym != mid and mid not in a_sym:
                    continue
                algo_id = a.get("algoId") or a.get("clientAlgoId")
                if algo_id is not None:
                    self._signed_request("DELETE", "/fapi/v1/algoOrder", {"algoId": algo_id})
                    n += 1
            except Exception as e:
                logger.debug(f"cancel algo: {e}")
        return n

    def cancel_all_orders(self, symbol: str = None) -> int:
        if self.mode == Mode.PAPER:
            if symbol:
                to_del = [k for k, o in self.paper_orders.items() if o.get("symbol") == symbol]
                for k in to_del:
                    del self.paper_orders[k]
                return len(to_del)
            n = len(self.paper_orders)
            self.paper_orders.clear()
            return n
        cancelled = 0
        symbols = [symbol] if symbol else []
        if not symbols:
            try:
                for p in self.get_positions():
                    symbols.append(p.symbol)
            except Exception:
                pass
        for sym in symbols:
            if not sym:
                continue
            try:
                self._signed_request("DELETE", "/fapi/v1/allOpenOrders", {"symbol": self._market_id(sym)})
                cancelled += 1
            except Exception as e:
                logger.debug(f"cancel orders {sym}: {e}")
            cancelled += self._cancel_algo_conditional(sym)
        return cancelled

    def cleanup_orphan_orders(self, extra_symbols: List[str] = None) -> int:
        if self.mode == Mode.PAPER:
            return 0
        pos_syms = {p.symbol for p in self.get_positions()}
        if extra_symbols:
            pos_syms |= set(extra_symbols)
        n = 0
        try:
            algos = self._fapi("/fapi/v1/openAlgoOrders", "GET", {}) or []
            if isinstance(algos, dict):
                algos = algos.get("orders") or algos.get("data") or []
            for a in algos or []:
                mid = str(a.get("symbol") or "")
                sym = self._algo_id_to_ccxt_symbol(mid)
                if sym in pos_syms or mid in {self._market_id(s) for s in pos_syms}:
                    continue
                algo_id = a.get("algoId") or a.get("clientAlgoId")
                if algo_id is not None:
                    try:
                        self._signed_request("DELETE", "/fapi/v1/algoOrder", {"algoId": algo_id})
                        n += 1
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"cleanup_orphan: {e}")
        return n

    def close_position(self, symbol: str, side: Side):
        if self.mode == Mode.PAPER:
            key = f"{symbol}_{side.value}"
            self.paper_positions.pop(key, None)
            return
        positions = self.get_positions()
        for p in positions:
            if p.symbol == symbol and p.side == side:
                close_side = "sell" if side == Side.LONG else "buy"
                self.create_order(symbol, close_side, p.size, order_type="market", params={"reduceOnly": True})
                self.cancel_all_orders(symbol)
                return

    def flatten_all(self):
        for p in self.get_positions():
            try:
                self.close_position(p.symbol, p.side)
            except Exception as e:
                logger.error(f"flatten {p.symbol}: {e}")
        self.cancel_all_orders()
        if self.mode == Mode.PAPER:
            self.paper_positions.clear()
