# Autotrade – Binance Futures Bot

Multi-agent Binance USDT-M Futures bot (paper / testnet / live).

## Features
- Scanner + multiple strategies (ORB, FVG, Order Block, MA Ribbon, …)
- Risk gate, ML signal filter, Discord control
- Robust exchange layer: REST for testnet, Algo Order API for SL/TP

## Quick complete import (recommended)

Repo is being filled in batches. To get **full working code** in one step:

```bash
# Clone both
git clone https://github.com/leha691312-pixel/binance_future_bot.git
git clone https://github.com/leha691312-pixel/autotrade.git
cd autotrade

# Copy all source from binance_future_bot
cp -a ../binance_future_bot/. .
rm -rf .git
git init
git remote add origin https://github.com/leha691312-pixel/autotrade.git

# Apply fixed exchange (testnet REST + algoOrder SL/TP)
# Download exchange_fixed.py from project artifacts or use the version below after it is pushed.
# For now, if core/exchange.py is missing, copy from binance_future_bot then patch:
#   - TESTNET_BASE = https://testnet.binancefuture.com
#   - load markets from /fapi/v1/exchangeInfo
#   - SL/TP via POST /fapi/v1/algoOrder

git add -A
git commit -m "Full bot + fixed exchange"
git branch -M main
git push -u origin main --force
```

## Setup
```bash
cp .env.example .env
# fill API keys (testnet or live)
pip install -r requirements.txt
python main.py
```

Mode is set in `config/settings.yaml` (`paper` | `testnet` | `live`).

## Exchange notes
`core/exchange.py` uses direct Futures REST on testnet (`testnet.binancefuture.com`) to avoid ccxt margin/sapi errors, and places SL/TP via `/fapi/v1/algoOrder`.
