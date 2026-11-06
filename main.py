"""
Main Orchestrator - Multi-agent trading bot
ML: R-label, time-split, collect_only, deploy gate
"""
import time
import yaml
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger

from utils.logger import setup_logger
from utils.status_writer import write_status
from utils.order_logger import OrderLogger
from core.exchange import ExchangeWrapper
from agents.risk_gate import RiskGate
from agents.scanner import ScannerAgent
from agents.execution import ExecutionAgent
from agents.ml_agent import MLAgent
from agents.discord_control import control_state, start_discord_in_thread
from agents.strategies import list_strategy_names

load_dotenv()


def load_config():
    with open(Path(__file__).parent / "config" / "settings.yaml", encoding="utf-8") as f:
        settings = yaml.safe_load(f)
    with open(Path(__file__).parent / "config" / "risk.yaml", encoding="utf-8") as f:
        risk = yaml.safe_load(f)
    return settings, risk


def _attach_ml_close_hook(risk_gate: RiskGate, ml_agent: MLAgent):
    orig = risk_gate.close_position

    def close_position(key: str, pnl: float):
        meta = {}
        pos = risk_gate.open_positions.get(key)
        if pos is not None:
            meta = {
                "strategy": getattr(pos, "strategy", "") or "",
                "timeframe": getattr(pos, "timeframe", "") or "",
                "trade_style": getattr(pos, "trade_style", "") or "",
                "symbol": getattr(pos, "symbol", ""),
                "size": float(getattr(pos, "size", 0) or 0),
                "entry": float(getattr(pos, "entry_price", 0) or 0),
                "sl": float(getattr(pos, "sl", 0) or 0),
            }
        orig(key, pnl)
        try:
            report = ml_agent.on_close(key, pnl, meta=meta)
            if report:
                if report.get("deployed"):
                    logger.info(f"ML retrain DEPLOYED: {report}")
                elif report.get("error"):
                    logger.warning(f"ML retrain skipped: {report}")
                else:
                    logger.info(f"ML retrain report: {report}")
        except Exception as e:
            logger.warning(f"ML on_close hook failed: {e}")

    risk_gate.close_position = close_position  # type: ignore
    risk_gate.ml_agent = ml_agent


def main():
    settings, risk_cfg = load_config()
    setup_logger(settings.get("log_file", "logs/bot.log"), settings.get("log_level", "INFO"))

    mode = settings.get("mode", "paper")
    logger.info(f"Starting bot mode={mode}")

    exchange = ExchangeWrapper(mode=mode, config=settings)
    risk_gate = RiskGate(risk_cfg)
    order_logger = OrderLogger()

    ml_agent = MLAgent(settings.get("ml") or {})
    _attach_ml_close_hook(risk_gate, ml_agent)

    ohlcv_cache = {}
    executor = ExecutionAgent(
        exchange,
        risk_gate,
        default_leverage=int(risk_cfg.get("default_leverage", 5)),
        max_leverage=int(risk_cfg.get("max_leverage", 10)),
        order_logger=order_logger,
        ml_agent=ml_agent,
        ohlcv_cache=ohlcv_cache,
    )

    enabled = settings.get("enabled_strategies") or list_strategy_names()
    scanner = ScannerAgent(
        exchange,
        enabled_strategies=enabled,
        top_n=int(settings.get("top_n", 30)),
        timeframes=settings.get("timeframes") or ["15m", "1h"],
        strategy_params=settings.get("strategy_params") or {},
        max_workers=int(settings.get("scan_workers", 16)),
        ohlcv_limit=int(settings.get("ohlcv_limit", 120)),
    )

    try:
        start_discord_in_thread()
    except Exception as e:
        logger.debug(f"Discord control skip: {e}")

    risk_gate.update_equity(exchange.get_balance())

    try:
        while True:
            if control_state.kill:
                logger.warning("Kill switch from Discord")
                risk_gate.kill_switch = True
                risk_gate.kill_reason = "discord"

            if risk_gate.kill_switch:
                write_status(
                    mode=mode,
                    kill_switch=True,
                    kill_reason=risk_gate.kill_reason,
                    equity=risk_gate.equity,
                    daily_pnl=risk_gate.daily_pnl,
                    open_positions=len(risk_gate.open_positions),
                )
                time.sleep(60)
                continue

            if control_state.paused:
                closed = risk_gate.handle_closed_positions(exchange, order_logger)
                invalidated = risk_gate.monitor_invalidations(exchange, order_logger)
                risk_gate.sync_positions_from_exchange(exchange)
                try:
                    exchange.cleanup_orphan_orders()
                except Exception as e:
                    logger.debug(f"cleanup_orphan_orders: {e}")
                control_state.last_cycle_info = f"PAUSED | closed={closed} invalidated={invalidated}"
                time.sleep(settings.get("scan_interval_seconds", 60))
                continue

            closed = risk_gate.handle_closed_positions(exchange, order_logger)
            invalidated = risk_gate.monitor_invalidations(exchange, order_logger)
            risk_gate.sync_positions_from_exchange(exchange)

            try:
                exchange.cleanup_orphan_orders()
            except Exception as e:
                logger.debug(f"cleanup_orphan_orders: {e}")

            if hasattr(scanner, "top_n"):
                scanner.top_n = int(settings.get("top_n", scanner.top_n))
            if hasattr(scanner, "max_workers") and settings.get("scan_workers") is not None:
                scanner.max_workers = max(2, min(int(settings.get("scan_workers", 16)), 24))
            if hasattr(scanner, "ohlcv_limit") and settings.get("ohlcv_limit") is not None:
                scanner.ohlcv_limit = max(60, int(settings.get("ohlcv_limit", 120)))
            if hasattr(scanner, "timeframes") and settings.get("timeframes"):
                scanner.timeframes = list(settings.get("timeframes"))

            if control_state.reload_strategies:
                control_state.reload_strategies = False
                enabled = settings.get("enabled_strategies") or list_strategy_names()
                scanner = ScannerAgent(
                    exchange,
                    enabled_strategies=enabled,
                    top_n=int(settings.get("top_n", 30)),
                    timeframes=settings.get("timeframes") or ["15m", "1h"],
                    strategy_params=settings.get("strategy_params") or {},
                    max_workers=int(settings.get("scan_workers", 16)),
                    ohlcv_limit=int(settings.get("ohlcv_limit", 120)),
                )

            raw_signals = scanner.scan()
            if hasattr(scanner, "last_dfs") and isinstance(scanner.last_dfs, dict):
                ohlcv_cache.clear()
                ohlcv_cache.update(scanner.last_dfs)

            signals = ml_agent.filter(raw_signals, dfs=ohlcv_cache if ohlcv_cache else None)

            executed = 0
            # Chi 1 lenh moi / cycle de tranh dong loat bi testnet dong som
            for sig in signals[:1]:
                if executor.execute(sig):
                    executed += 1

            pos_list = []
            try:
                for p in exchange.get_positions():
                    pos_list.append({
                        "symbol": p.symbol,
                        "side": p.side.value if hasattr(p.side, "value") else str(p.side),
                        "entry": p.entry_price,
                        "size": p.size,
                        "sl": p.sl,
                        "tp": p.tp,
                        "upnl": p.unrealized_pnl,
                    })
            except Exception:
                pass

            ml_st = ml_agent.status()
            write_status(
                mode=mode,
                kill_switch=risk_gate.kill_switch,
                kill_reason=risk_gate.kill_reason,
                equity=risk_gate.equity,
                daily_pnl=risk_gate.daily_pnl,
                open_positions=len(risk_gate.open_positions) or len(pos_list),
                consecutive_losses=risk_gate.consecutive_losses,
                raw_signals=len(raw_signals),
                filtered_signals=len(signals),
                executed=executed,
                recent_signals=[s.to_dict() for s in signals[:15]],
                positions=pos_list,
                strategies=[s.name for s in scanner.strategies],
                ml=ml_st,
            )

            logger.info(
                f"Cycle | raw={len(raw_signals)} filtered={len(signals)} "
                f"exec={executed} closed={closed} inv={invalidated} ml={ml_st}"
            )
            time.sleep(settings.get("scan_interval_seconds", 60))

    except KeyboardInterrupt:
        logger.info("Shutting down (Ctrl+C) – positions left open")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        write_status(mode=mode, last_error=str(e)[:200], kill_switch=risk_gate.kill_switch)


if __name__ == "__main__":
    main()
