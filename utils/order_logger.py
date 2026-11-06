from pathlib import Path
from datetime import datetime
from loguru import logger

class OrderLogger:
    def __init__(self, path: str = "data/orders.xlsx"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._rows = []

    def log(self, **kwargs):
        row = {"ts": datetime.utcnow().isoformat(), **kwargs}
        self._rows.append(row)
        try:
            import pandas as pd
            df = pd.DataFrame(self._rows)
            df.to_excel(self.path, index=False)
        except Exception as e:
            logger.debug(f"order_logger: {e}")
