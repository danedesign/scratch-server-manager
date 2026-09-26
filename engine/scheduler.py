from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler

from engine.logger import get_logger

logger = get_logger()


class PromotionScheduler:
    """Thin wrapper around APScheduler's BackgroundScheduler. Runs jobs on their
    own thread pool, so this never blocks the Flask dashboard or the file watchers.

    Callers must only call schedule() when a job is new or its settings actually
    changed - add_job(replace_existing=True) recreates the job and resets its
    next-run countdown even when called with identical args (confirmed empirically),
    so calling it unconditionally on every config reload would reset every folder's
    promotion timer whenever any unrelated folder's config changed."""

    def __init__(self):
        self._scheduler = BackgroundScheduler()
        self._scheduler.start()

    def schedule(self, job_id: str, interval_minutes: int, func: Callable) -> None:
        self._scheduler.add_job(func, "interval", minutes=interval_minutes, id=job_id, replace_existing=True)

    def unschedule(self, job_id: str) -> None:
        if self._scheduler.get_job(job_id) is not None:
            self._scheduler.remove_job(job_id)

    def next_run(self, job_id: str):
        job = self._scheduler.get_job(job_id)
        return job.next_run_time if job else None

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)
