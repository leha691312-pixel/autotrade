"""
ML Agent - signal filter + sample collection + optional retrain
"""
from typing import List, Optional, Dict, Any
from pathlib import Path
import json
from datetime import datetime
from loguru import logger
from core.models import Signal


class MLAgent:
    def __init__(
        self,
        model_path: str = "data/models/signal_filter.joblib",
        samples_path: str = "data/models/train_samples.jsonl",
        min_samples: int = 80,
        retrain_every_new: int = 25,
        min_retrain_hours: float = 12,
        collect_only: bool = True,
        filter_enabled: bool = True,
        min_auc_deploy: float = 0.55,
        min_class_count: int = 20,
        fee_rate: float = 0.0004,
        min_r_multiple: float = 0.25,
        prob_threshold: float = 0.55,
        test_ratio: float = 0.25,
    ):
        self.model_path = Path(model_path)
        self.samples_path = Path(samples_path)
        self.min_samples = min_samples
        self.retrain_every_new = retrain_every_new
        self.min_retrain_hours = min_retrain_hours
        self.collect_only = collect_only
        self.filter_enabled = filter_enabled
        self.min_auc_deploy = min_auc_deploy
        self.min_class_count = min_class_count
        self.fee_rate = fee_rate
        self.min_r_multiple = min_r_multiple
        self.prob_threshold = prob_threshold
        self.test_ratio = test_ratio
        self.model = None
        self._open_meta: Dict[str, dict] = {}
        self._new_since_train = 0
        self._last_train = None
        self.samples_path.parent.mkdir(parents=True, exist_ok=True)
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        self._try_load_model()

    def _try_load_model(self):
        try:
            if self.model_path.exists():
                import joblib
                self.model = joblib.load(self.model_path)
                logger.info(f"ML model loaded: {self.model_path}")
        except Exception as e:
            logger.debug(f"ML load skip: {e}")
            self.model = None

    def status(self) -> dict:
        n = 0
        try:
            if self.samples_path.exists():
                n = sum(1 for _ in self.samples_path.open())
        except Exception:
            pass
        return {
            "collect_only": self.collect_only,
            "filter_enabled": self.filter_enabled,
            "model_loaded": self.model is not None,
            "samples": n,
            "new_since_train": self._new_since_train,
        }

    def filter(self, signals: List[Signal], dfs: dict = None) -> List[Signal]:
        if not signals:
            return []
        if self.collect_only or not self.filter_enabled or self.model is None:
            return signals
        # Pass-through until model trained; keep API compatible
        return signals

    def on_open(self, signal: Signal, df=None, extra: dict = None):
        key = f"{signal.symbol}_{signal.side.value}"
        self._open_meta[key] = {
            "signal": signal.to_dict(),
            "extra": extra or {},
            "ts": datetime.utcnow().isoformat(),
        }

    def on_close(self, key: str, pnl: float, meta: dict = None) -> Optional[dict]:
        meta = meta or {}
        sample = {
            "key": key,
            "pnl": pnl,
            "meta": meta,
            "open": self._open_meta.pop(key, {}),
            "ts": datetime.utcnow().isoformat(),
        }
        try:
            with self.samples_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
            self._new_since_train += 1
        except Exception as e:
            logger.debug(f"ML sample write: {e}")
        return {"saved": True, "pnl": pnl}

    def train_demo(self) -> dict:
        return {"status": "demo", "message": "Use real samples to train"}
