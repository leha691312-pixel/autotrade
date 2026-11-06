import json
from pathlib import Path
from datetime import datetime
from loguru import logger

def write_status(**kwargs):
    path = Path("data/status.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"updated_at": datetime.utcnow().isoformat(), **kwargs}
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug(f"write_status: {e}")
