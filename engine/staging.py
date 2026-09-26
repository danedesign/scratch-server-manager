import json
import shutil
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from engine.alerting import send_alert
from engine.integrity import IntegrityResult
from engine.logger import get_logger

IntegrityCheck = Callable[[Path], IntegrityResult]

logger = get_logger()

# Tracks the last reason a given vault was alerted for, so a folder that's stuck
# failing (e.g. retried hourly by engine/scheduler.py) alerts once per distinct
# failure, not once per retry forever. Cleared on the next successful promotion,
# so a problem that recurs later - even with the same reason - alerts again.
_last_alert_reason: dict[Path, str] = {}


@dataclass
class PromotionResult:
    promoted: bool
    reason: str


def promote(
    staging_path: Path,
    vault_path: Path,
    integrity_check: IntegrityCheck,
    keep_failed_staging: bool = True,
    machine_id: str = "",
) -> PromotionResult:
    staging_path = Path(staging_path)
    vault_path = Path(vault_path)
    machine_id = machine_id or socket.gethostname()

    result = integrity_check(staging_path)
    if not result.ok:
        logger.warning("Integrity check failed for %s: %s", staging_path, result.reason)
        if keep_failed_staging:
            quarantine = _quarantine_path(staging_path)
            shutil.copytree(staging_path, quarantine)
            logger.warning("Failed staging copy preserved at %s for inspection", quarantine)
        if _last_alert_reason.get(vault_path) != result.reason:
            send_alert(f"Promotion skipped for {vault_path}: {result.reason}")
            _last_alert_reason[vault_path] = result.reason
        else:
            logger.info("Suppressing repeat alert for %s (same failure reason as last alert)", vault_path)
        return PromotionResult(promoted=False, reason=result.reason)

    _last_alert_reason.pop(vault_path, None)
    _check_single_writer(vault_path, machine_id)
    _atomic_replace_dir(staging_path, vault_path)
    _record_promotion(vault_path, machine_id)
    logger.info("Promoted %s -> %s (machine=%s)", staging_path, vault_path, machine_id)
    return PromotionResult(promoted=True, reason=result.reason)


def _state_path(vault_path: Path) -> Path:
    return vault_path.parent / f"{vault_path.name}.promotion-state.json"


def _check_single_writer(vault_path: Path, machine_id: str) -> None:
    state_path = _state_path(vault_path)
    if not state_path.exists():
        return
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        return
    last_machine = state.get("machine")
    if last_machine and last_machine != machine_id:
        logger.warning(
            "Promotion from %s follows a promotion from %s at %s - verify only one machine is active",
            machine_id, last_machine, state.get("promoted_at"),
        )


def _record_promotion(vault_path: Path, machine_id: str) -> None:
    state = {"machine": machine_id, "promoted_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _state_path(vault_path).write_text(json.dumps(state))


def _quarantine_path(staging_path: Path) -> Path:
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    candidate = staging_path.parent / f"{staging_path.name}.failed-{timestamp}"
    counter = 1
    while candidate.exists():
        candidate = staging_path.parent / f"{staging_path.name}.failed-{timestamp}-{counter}"
        counter += 1
    return candidate


def _atomic_replace_dir(source: Path, dest: Path) -> None:
    # os.rename() can't drop a new directory straight onto an existing non-empty one
    # (POSIX requires the target be empty), so the swap is two renames: move the old
    # vault out of the way, then move the new one in. Each rename is atomic; the
    # instant between them where `dest` briefly doesn't exist is the residual risk.
    dest.parent.mkdir(parents=True, exist_ok=True)
    staged_new = dest.parent / f"{dest.name}.new"
    if staged_new.exists():
        shutil.rmtree(staged_new)
    shutil.copytree(source, staged_new)

    if dest.exists():
        old = dest.parent / f"{dest.name}.old-{time.strftime('%Y%m%dT%H%M%S')}"
        if old.exists():
            # Leftover from a previous run that died before cleanup; it's stale, not live.
            shutil.rmtree(old)
        dest.rename(old)
        staged_new.rename(dest)
        shutil.rmtree(old)
    else:
        staged_new.rename(dest)
