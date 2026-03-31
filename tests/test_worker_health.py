from shot_scraper_api.worker_health import assess_worker_health


def test_assess_worker_health_is_healthy_with_recent_heartbeat() -> None:
    healthy, detail = assess_worker_health(
        heartbeat_age_seconds=5.0,
        queued_jobs=0,
        processing_jobs=0,
        queued_oldest_age_seconds=0.0,
        heartbeat_timeout_seconds=45,
        stalled_queue_threshold_seconds=180,
        check_queue_stall=True,
    )

    assert healthy is True
    assert detail == "ok"


def test_assess_worker_health_fails_when_heartbeat_missing() -> None:
    healthy, detail = assess_worker_health(
        heartbeat_age_seconds=None,
        queued_jobs=0,
        processing_jobs=0,
        queued_oldest_age_seconds=0.0,
        heartbeat_timeout_seconds=45,
        stalled_queue_threshold_seconds=180,
        check_queue_stall=True,
    )

    assert healthy is False
    assert detail == "worker heartbeat missing"


def test_assess_worker_health_fails_when_queue_is_stalled() -> None:
    healthy, detail = assess_worker_health(
        heartbeat_age_seconds=5.0,
        queued_jobs=11,
        processing_jobs=0,
        queued_oldest_age_seconds=240.0,
        heartbeat_timeout_seconds=45,
        stalled_queue_threshold_seconds=180,
        check_queue_stall=True,
    )

    assert healthy is False
    assert detail.startswith("queue stalled")


def test_assess_worker_health_ignores_queue_stall_when_disabled() -> None:
    healthy, detail = assess_worker_health(
        heartbeat_age_seconds=5.0,
        queued_jobs=11,
        processing_jobs=0,
        queued_oldest_age_seconds=240.0,
        heartbeat_timeout_seconds=45,
        stalled_queue_threshold_seconds=180,
        check_queue_stall=False,
    )

    assert healthy is True
    assert detail == "ok"
