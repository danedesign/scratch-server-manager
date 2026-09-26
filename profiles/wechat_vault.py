import time
from functools import partial
from pathlib import Path
from typing import Optional

from engine.integrity import wechat_vault_integrity_check
from engine.logger import get_logger
from engine.staging import PromotionResult, promote


class WeChatVaultProfile:
    """Promotes a staged WeChat data folder to the live vault, gated on a SQLite-aware
    integrity check. No scheduling here yet — interval/automatic promotion is wired up
    once engine/scheduler.py exists; for now promote_now() is called explicitly."""

    def __init__(
        self,
        staging_path: Path,
        vault_path: Path,
        keep_failed_staging: bool = True,
        max_drop_ratio: float = 0.2,
    ):
        self.staging_path = Path(staging_path)
        self.vault_path = Path(vault_path)
        self.keep_failed_staging = keep_failed_staging
        self.max_drop_ratio = max_drop_ratio
        self._logger = get_logger()
        self.last_attempt_at: Optional[float] = None
        self.last_result: Optional[PromotionResult] = None

    def promote_now(self, machine_id: str = "") -> PromotionResult:
        self.last_attempt_at = time.time()
        last_good = self.vault_path if self.vault_path.is_dir() else None
        integrity_check = partial(
            wechat_vault_integrity_check,
            last_good_path=last_good,
            max_drop_ratio=self.max_drop_ratio,
        )
        result = promote(
            self.staging_path,
            self.vault_path,
            integrity_check,
            keep_failed_staging=self.keep_failed_staging,
            machine_id=machine_id,
        )
        self.last_result = result
        return result
