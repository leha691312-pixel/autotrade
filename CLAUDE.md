# Autotrade notes

Exchange layer (`core/exchange.py`) was rewritten for testnet reliability:
- Base URL: testnet.binancefuture.com (no set_sandbox_mode)
- Markets from /fapi/v1/exchangeInfo via REST
- Balance / positions via signed REST
- SL/TP via /fapi/v1/algoOrder (STOP_MARKET, TAKE_PROFIT_MARKET)

Source of full bot: binance_future_bot. Fixed exchange also in project artifacts as exchange_fixed.py if needed.
