from loguru import logger
import sys
from pathlib import Path

def setup_logger(log_file: str = "logs/bot.log", level: str = "INFO"):
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=level, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
    logger.add(log_file, level=level, rotation="10 MB", retention="7 days", encoding="utf-8")
    return logger
