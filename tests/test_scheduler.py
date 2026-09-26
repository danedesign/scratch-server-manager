import threading
import time

import pytest

from engine.scheduler import PromotionScheduler


@pytest.fixture
def scheduler():
    s = PromotionScheduler()
    try:
        yield s
    finally:
        s.shutdown()


def test_schedule_creates_a_job_with_next_run(scheduler):
    scheduler.schedule("job1", 60, lambda: None)
    assert scheduler.next_run("job1") is not None


def test_next_run_none_for_unknown_job(scheduler):
    assert scheduler.next_run("nope") is None


def test_unschedule_removes_the_job(scheduler):
    scheduler.schedule("job1", 60, lambda: None)
    scheduler.unschedule("job1")
    assert scheduler.next_run("job1") is None


def test_unschedule_unknown_job_does_not_raise(scheduler):
    scheduler.unschedule("never-scheduled")  # must not raise


def test_replace_existing_resets_next_run_time(scheduler):
    """Documents the real trap this project's Manager.reload() has to work
    around: rescheduling with identical settings still resets the countdown."""
    scheduler.schedule("job1", 10, lambda: None)
    first = scheduler.next_run("job1")
    time.sleep(1.1)
    scheduler.schedule("job1", 10, lambda: None)
    second = scheduler.next_run("job1")
    assert second > first


@pytest.mark.slow
def test_job_actually_fires(scheduler):
    fired = threading.Event()
    scheduler.schedule("job1", 1, fired.set)  # APScheduler's minimum granularity is minutes
    assert fired.wait(timeout=75), "job did not fire within 75s of a 1-minute schedule"
