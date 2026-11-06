# Autotrade – Binance Futures Bot

Multi-agent Binance USDT-M Futures bot (paper / testnet / live).

## Features
- Scanner + multiple strategies (ORB, FVG, Order Block, MA Ribbon, …)
- Risk gate, ML signal filter, Discord control
- Robust exchange layer: REST for testnet, Algo Order API for SL/TP

## Setup
```bash
cp .env.example .env
# fill API keys
pip install -r requirements.txt
python main.py
```

Mode is set in `config/settings.yaml` (`paper` | `testnet` | `live`).

## Exchange notes
`core/exchange.py` uses direct Futures REST on testnet (`testnet.binancefuture.com`) to avoid ccxt margin/sapi errors, and places SL/TP via `/fapi/v1/algoOrder`.
