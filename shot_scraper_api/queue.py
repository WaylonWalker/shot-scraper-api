import enum
import json
import time
from typing import Optional, Dict, Any, List

import diskcache
from redis import Redis

from shot_scraper_api.config import config
from shot_scraper_api.screenshot import build_image_name


class JobStatus(enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


def _safe_avg(values: List[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 3)


def _build_job_stats(job_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build queue and timing stats from job rows."""
    now = time.time()
    stats: Dict[str, Any] = {status.value: 0 for status in JobStatus}
    stats["total"] = 0

    completed_durations: List[float] = []
    terminal_durations: List[float] = []
    queued_ages: List[float] = []
    processing_ages: List[float] = []
    completed_last_hour = 0

    for row in job_rows:
        status = row.get("status")
        created_at = row.get("created_at")
        updated_at = row.get("updated_at")
        started_processing_at = row.get("started_processing_at")

        if status in stats:
            stats[status] += 1
        stats["total"] += 1

        if isinstance(created_at, (int, float)) and isinstance(
            updated_at, (int, float)
        ):
            duration = max(0.0, updated_at - created_at)
            if status in [JobStatus.COMPLETED.value, JobStatus.FAILED.value]:
                terminal_durations.append(duration)

        if isinstance(started_processing_at, (int, float)) and isinstance(
            updated_at, (int, float)
        ):
            processing_duration = max(0.0, updated_at - started_processing_at)
            if status == JobStatus.COMPLETED.value:
                completed_durations.append(processing_duration)

        if status == JobStatus.QUEUED.value and isinstance(created_at, (int, float)):
            queued_ages.append(max(0.0, now - created_at))

        if status == JobStatus.PROCESSING.value and isinstance(
            started_processing_at, (int, float)
        ):
            processing_ages.append(max(0.0, now - started_processing_at))

        if (
            status == JobStatus.COMPLETED.value
            and isinstance(updated_at, (int, float))
            and updated_at >= now - 3600
        ):
            completed_last_hour += 1

    terminal_total = stats[JobStatus.COMPLETED.value] + stats[JobStatus.FAILED.value]
    success_rate = (
        round((stats[JobStatus.COMPLETED.value] / terminal_total) * 100, 2)
        if terminal_total
        else 0.0
    )

    stats["avg_processing_time_seconds"] = _safe_avg(completed_durations)
    stats["avg_terminal_time_seconds"] = _safe_avg(terminal_durations)
    stats["queued_avg_age_seconds"] = _safe_avg(queued_ages)
    stats["queued_oldest_age_seconds"] = (
        round(max(queued_ages), 3) if queued_ages else 0.0
    )
    stats["processing_avg_age_seconds"] = _safe_avg(processing_ages)
    stats["success_rate_percent"] = success_rate
    stats["completed_last_hour"] = completed_last_hour

    return stats


class QueueBase:
    def add_job(
        self,
        url: str,
        width: int = 800,
        height: int = 450,
        selectors: Optional[str] = None,
        format: str = "webp",
        scaled_width: Optional[int] = None,
        scaled_height: Optional[int] = None,
        version: Optional[int] = None,
        timeout: Optional[int] = None,
        theme: Optional[str] = None,
        priority: int = 0,
    ) -> str:
        raise NotImplementedError

    def get_next_job(self) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error: Optional[str] = None,
        filename: Optional[str] = None,
    ):
        raise NotImplementedError

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def get_job_status(self, job_id: str) -> Optional[JobStatus]:
        raise NotImplementedError

    def get_job_id_by_filename(self, filename: str) -> Optional[str]:
        raise NotImplementedError

    def is_shot_queued_or_processing(
        self,
        url: str,
        width: int,
        height: int,
        selectors: Optional[str] = None,
        version: Optional[int] = None,
        scaled_width: Optional[int] = None,
        scaled_height: Optional[int] = None,
        format: str = "webp",
        theme: Optional[str] = None,
    ) -> bool:
        raise NotImplementedError

    def get_queue_stats(self) -> Dict[str, Any]:
        raise NotImplementedError

    def record_url_request(self, url: str, filename: str, method: str) -> None:
        raise NotImplementedError

    def get_url_stats(
        self,
        limit: Optional[int] = None,
        offset: int = 0,
        filenames_per_url: Optional[int] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def get_active_jobs(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def cleanup_old_jobs(
        self,
        max_age_hours: int = 24,
        stale_age_minutes: int = 30,
        dry_run: bool = False,
    ) -> Dict[str, int]:
        raise NotImplementedError

    def record_worker_heartbeat(
        self, worker_id: str, timestamp: Optional[float] = None
    ) -> None:
        raise NotImplementedError

    def get_worker_heartbeat(self, worker_id: str) -> Optional[float]:
        raise NotImplementedError


def _build_url_stats(
    url_rows: List[Dict[str, Any]],
    limit: Optional[int] = None,
    offset: int = 0,
    filenames_per_url: Optional[int] = None,
) -> Dict[str, Any]:
    """Build aggregate URL request stats from stored rows."""
    sorted_rows = sorted(
        url_rows,
        key=lambda row: (
            -int(row.get("request_count", 0)),
            -float(row.get("last_requested_at", 0.0)),
            str(row.get("url", "")),
        ),
    )
    total_urls = len(sorted_rows)
    if offset < 0:
        offset = 0
    if isinstance(limit, int) and limit > 0:
        sorted_rows = sorted_rows[offset : offset + limit]
    elif offset:
        sorted_rows = sorted_rows[offset:]

    trimmed_rows = []
    for row in sorted_rows:
        filenames = row.get("filenames", [])
        if not isinstance(filenames, list):
            filenames = []
        total_filenames = len(filenames)
        if isinstance(filenames_per_url, int) and filenames_per_url > 0:
            filenames = filenames[:filenames_per_url]

        trimmed_rows.append(
            {
                **row,
                "filenames": filenames,
                "total_filenames": total_filenames,
                "truncated_filenames": max(0, total_filenames - len(filenames)),
            }
        )

    return {
        "total_urls": total_urls,
        "shown_urls": len(trimmed_rows),
        "offset": offset,
        "total_requests": sum(int(row.get("request_count", 0)) for row in url_rows),
        "urls": trimmed_rows,
    }


def _build_active_jobs(job_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return queued and processing jobs ordered by activity."""
    active_statuses = {JobStatus.QUEUED.value, JobStatus.PROCESSING.value}
    rows = [row for row in job_rows if row.get("status") in active_statuses]
    rows.sort(
        key=lambda row: (
            0 if row.get("status") == JobStatus.PROCESSING.value else 1,
            -int(row.get("priority", 0)),
            float(row.get("created_at", 0.0)),
        )
    )
    return rows


class ScreenshotQueue(QueueBase):
    def __init__(self, cache_dir: str = "/tmp/shot-scraper-queue"):
        self.cache = diskcache.Cache(cache_dir)
        self.job_counter_key = "job_counter"
        self.job_index_key = "job_by_filename"
        self.url_stats_key = "url_request_stats"
        self.worker_heartbeat_key = "worker_heartbeats"

    def _get_next_job_id(self) -> str:
        """Get next job ID"""
        job_id = self.cache.incr(self.job_counter_key)
        return f"job_{int(time.time())}_{job_id}"

    def add_job(
        self,
        url: str,
        width: int = 800,
        height: int = 450,
        selectors: Optional[str] = None,
        format: str = "webp",
        scaled_width: Optional[int] = None,
        scaled_height: Optional[int] = None,
        version: Optional[int] = None,
        timeout: Optional[int] = None,
        theme: Optional[str] = None,
        priority: int = 0,
    ) -> str:
        """Add a screenshot job to the queue"""
        with self.cache.transact():
            job_id = self._get_next_job_id()
            scaled_width = scaled_width or width
            scaled_height = scaled_height or height
            selector_list = selectors.split(",") if selectors else []
            expected_filename = build_image_name(
                url,
                selector_list,
                width,
                height,
                scaled_width,
                scaled_height,
                format,
                version,
                theme,
            )

            job_data = {
                "job_id": job_id,
                "url": url,
                "width": width,
                "height": height,
                "selectors": selectors,
                "format": format,
                "scaled_width": scaled_width,
                "scaled_height": scaled_height,
                "version": version,
                "timeout": timeout,
                "theme": theme,
                "priority": priority,
                "status": JobStatus.QUEUED.value,
                "created_at": time.time(),
                "updated_at": time.time(),
                "started_processing_at": None,
                "error": None,
                "filename": expected_filename,
            }

            self.cache.set(f"job:{job_id}", job_data)

            filename_index_raw = self.cache.get(self.job_index_key)
            filename_index = (
                filename_index_raw if isinstance(filename_index_raw, dict) else {}
            )
            filename_index[expected_filename] = job_id
            self.cache.set(self.job_index_key, filename_index)

            queue_key = f"queue:priority:{priority}"
            existing_jobs_raw = self.cache.get(queue_key)
            existing_jobs = (
                existing_jobs_raw if isinstance(existing_jobs_raw, list) else []
            )
            existing_jobs.append(job_id)
            self.cache.set(queue_key, existing_jobs)

            return job_id

    def get_next_job(self) -> Optional[Dict[str, Any]]:
        """Get the next job from the queue"""
        with self.cache.transact():
            for priority in range(10, -1, -1):
                queue_key = f"queue:priority:{priority}"
                job_ids_raw = self.cache.get(queue_key)
                job_ids = job_ids_raw if isinstance(job_ids_raw, list) else []

                if job_ids:
                    job_id = str(job_ids[0])
                    job_data = self.get_job(job_id)

                    if job_data and job_data["status"] == JobStatus.QUEUED.value:
                        remaining_job_ids = job_ids[1:]
                        if remaining_job_ids:
                            self.cache.set(queue_key, remaining_job_ids)
                        else:
                            self.cache.delete(queue_key)
                        return job_data

        return None

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error: Optional[str] = None,
        filename: Optional[str] = None,
    ):
        """Update job status"""
        job_data = self.get_job(job_id)
        if job_data:
            job_data["status"] = status.value
            now = time.time()
            job_data["updated_at"] = now
            if status == JobStatus.PROCESSING and not isinstance(
                job_data.get("started_processing_at"), (int, float)
            ):
                job_data["started_processing_at"] = now
            if error:
                job_data["error"] = error
            if filename:
                job_data["filename"] = filename
            self.cache.set(f"job:{job_id}", job_data)
            if status in [JobStatus.COMPLETED, JobStatus.FAILED]:
                filename_index_raw = self.cache.get(self.job_index_key)
                filename_index = (
                    filename_index_raw if isinstance(filename_index_raw, dict) else {}
                )
                if job_data.get("filename") in filename_index:
                    del filename_index[job_data["filename"]]
                    self.cache.set(self.job_index_key, filename_index)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job data by ID"""
        job_data = self.cache.get(f"job:{job_id}")
        if not isinstance(job_data, dict):
            return None
        return job_data

    def get_job_status(self, job_id: str) -> Optional[JobStatus]:
        """Get job status by ID"""
        job_data = self.get_job(job_id)
        if job_data:
            return JobStatus(job_data["status"])
        return None

    def get_job_id_by_filename(self, filename: str) -> Optional[str]:
        filename_index_raw = self.cache.get(self.job_index_key)
        filename_index = (
            filename_index_raw if isinstance(filename_index_raw, dict) else {}
        )
        return filename_index.get(filename)

    def is_shot_queued_or_processing(
        self,
        url: str,
        width: int,
        height: int,
        selectors: Optional[str] = None,
        version: Optional[int] = None,
        scaled_width: Optional[int] = None,
        scaled_height: Optional[int] = None,
        format: str = "webp",
        theme: Optional[str] = None,
    ) -> bool:
        """Check if a shot with the same parameters is already queued or processing"""
        scaled_width = scaled_width or width
        scaled_height = scaled_height or height
        selector_list = selectors.split(",") if selectors else []
        expected_filename = build_image_name(
            url,
            selector_list,
            width,
            height,
            scaled_width,
            scaled_height,
            format,
            version,
            theme,
        )

        filename_index_raw = self.cache.get(self.job_index_key)
        filename_index = (
            filename_index_raw if isinstance(filename_index_raw, dict) else {}
        )
        job_id = filename_index.get(expected_filename)
        if not job_id:
            return False

        job_data = self.get_job(job_id)
        if not job_data:
            return False

        return job_data["status"] in [
            JobStatus.QUEUED.value,
            JobStatus.PROCESSING.value,
        ]

    def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        jobs: List[Dict[str, Any]] = []

        for key in list(self.cache.iterkeys()):
            if isinstance(key, str) and key.startswith("job:"):
                job_data = self.cache.get(key)
                if job_data and isinstance(job_data, dict):
                    jobs.append(job_data)

        return _build_job_stats(jobs)

    def get_active_jobs(self) -> List[Dict[str, Any]]:
        """List queued and processing jobs."""
        jobs: List[Dict[str, Any]] = []
        for key in list(self.cache.iterkeys()):
            if isinstance(key, str) and key.startswith("job:"):
                job_data = self.cache.get(key)
                if job_data and isinstance(job_data, dict):
                    jobs.append(job_data)
        return _build_active_jobs(jobs)

    def record_url_request(self, url: str, filename: str, method: str) -> None:
        """Record a request for a source URL and generated filename."""
        now = time.time()
        url_stats_raw = self.cache.get(self.url_stats_key)
        url_stats = url_stats_raw if isinstance(url_stats_raw, dict) else {}
        row = url_stats.get(url, {})
        filenames = row.get("filenames", [])
        if filename not in filenames:
            filenames.append(filename)

        method_counts_raw = row.get("method_counts", {})
        method_counts = method_counts_raw if isinstance(method_counts_raw, dict) else {}
        method_counts[method] = int(method_counts.get(method, 0)) + 1

        url_stats[url] = {
            "url": url,
            "request_count": int(row.get("request_count", 0)) + 1,
            "filenames": sorted(filenames),
            "first_requested_at": float(row.get("first_requested_at", now)),
            "last_requested_at": now,
            "method_counts": method_counts,
        }
        self.cache.set(self.url_stats_key, url_stats)

    def get_url_stats(
        self,
        limit: Optional[int] = None,
        offset: int = 0,
        filenames_per_url: Optional[int] = None,
    ) -> Dict[str, Any]:
        """List tracked URL request counts and generated files."""
        url_stats_raw = self.cache.get(self.url_stats_key)
        url_stats = url_stats_raw if isinstance(url_stats_raw, dict) else {}
        return _build_url_stats(
            list(url_stats.values()),
            limit=limit,
            offset=offset,
            filenames_per_url=filenames_per_url,
        )

    def cleanup_old_jobs(
        self,
        max_age_hours: int = 24,
        stale_age_minutes: int = 30,
        dry_run: bool = False,
    ) -> Dict[str, int]:
        """Clean up old completed/failed jobs and stale queued/processing jobs."""
        cutoff_time = time.time() - (max_age_hours * 3600)
        stale_cutoff_time = time.time() - (stale_age_minutes * 60)
        removed_counts = {"completed": 0, "failed": 0, "queued": 0, "processing": 0}
        removed_job_ids: set[str] = set()

        for key in list(self.cache.iterkeys()):
            if not (isinstance(key, str) and key.startswith("job:")):
                continue
            job_data = self.cache.get(key)
            if not (job_data and isinstance(job_data, dict)):
                continue

            status = str(job_data.get("status", ""))
            updated_at = float(job_data.get("updated_at", 0) or 0)
            created_at = float(job_data.get("created_at", 0) or 0)
            started_processing_at = float(job_data.get("started_processing_at", 0) or 0)
            should_remove = False

            if status in [JobStatus.COMPLETED.value, JobStatus.FAILED.value]:
                should_remove = updated_at < cutoff_time
            elif status == JobStatus.QUEUED.value:
                should_remove = created_at < stale_cutoff_time
            elif status == JobStatus.PROCESSING.value:
                marker = started_processing_at or updated_at or created_at
                should_remove = marker < stale_cutoff_time

            if not should_remove:
                continue

            removed_counts[status] += 1
            removed_job_ids.add(str(job_data["job_id"]))
            if dry_run:
                continue

            self.cache.delete(key)
            filename_index_raw = self.cache.get(self.job_index_key)
            filename_index = (
                filename_index_raw if isinstance(filename_index_raw, dict) else {}
            )
            if job_data.get("filename") in filename_index:
                del filename_index[job_data["filename"]]
                self.cache.set(self.job_index_key, filename_index)

        if removed_job_ids and not dry_run:
            for priority in range(10, -1, -1):
                queue_key = f"queue:priority:{priority}"
                job_ids_raw = self.cache.get(queue_key)
                job_ids = job_ids_raw if isinstance(job_ids_raw, list) else []
                filtered = [
                    job_id for job_id in job_ids if str(job_id) not in removed_job_ids
                ]
                if filtered != job_ids:
                    if filtered:
                        self.cache.set(queue_key, filtered)
                    else:
                        self.cache.delete(queue_key)

        return removed_counts

    def record_worker_heartbeat(
        self, worker_id: str, timestamp: Optional[float] = None
    ) -> None:
        heartbeats_raw = self.cache.get(self.worker_heartbeat_key)
        heartbeats = heartbeats_raw if isinstance(heartbeats_raw, dict) else {}
        heartbeats[worker_id] = float(
            timestamp if timestamp is not None else time.time()
        )
        self.cache.set(self.worker_heartbeat_key, heartbeats)

    def get_worker_heartbeat(self, worker_id: str) -> Optional[float]:
        heartbeats_raw = self.cache.get(self.worker_heartbeat_key)
        heartbeats = heartbeats_raw if isinstance(heartbeats_raw, dict) else {}
        value = heartbeats.get(worker_id)
        return float(value) if isinstance(value, (int, float)) else None


class RedisQueue(QueueBase):
    def __init__(self, redis_url: str, namespace: str = "shot-scraper"):
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.namespace = namespace
        self.job_counter_key = f"{namespace}:job_counter"
        self.queue_key = f"{namespace}:queue"
        self.processing_key = f"{namespace}:processing"
        self.job_key_prefix = f"{namespace}:job:"
        self.job_index_prefix = f"{namespace}:job_by_filename:"
        self.stats_key = f"{namespace}:stats"
        self.completed_timestamps_key = f"{namespace}:completed_timestamps"
        self.url_stats_key = f"{namespace}:url_request_stats"
        self.worker_heartbeats_key = f"{namespace}:worker_heartbeats"

    def _rebuild_stats(self) -> None:
        """Rebuild aggregate stats from stored jobs."""
        stats = {status.value: 0 for status in JobStatus}
        stats["total"] = 0
        completed_duration_sum = 0.0
        completed_duration_count = 0
        terminal_duration_sum = 0.0
        terminal_duration_count = 0
        completed_timestamps = []

        for key in self.redis.scan_iter(match=f"{self.job_key_prefix}*"):
            job_data = self.redis.get(key)
            if not job_data:
                continue
            data = json.loads(job_data)
            status = data.get("status")
            created_at = data.get("created_at")
            updated_at = data.get("updated_at")

            if status in stats:
                stats[status] += 1
            stats["total"] += 1

            if isinstance(created_at, (int, float)) and isinstance(
                updated_at, (int, float)
            ):
                duration = max(0.0, updated_at - created_at)
                if status == JobStatus.COMPLETED.value:
                    completed_duration_sum += duration
                    completed_duration_count += 1
                if status in [JobStatus.COMPLETED.value, JobStatus.FAILED.value]:
                    terminal_duration_sum += duration
                    terminal_duration_count += 1

            if status == JobStatus.COMPLETED.value and isinstance(
                updated_at, (int, float)
            ):
                completed_timestamps.append((data.get("job_id"), updated_at))

        pipeline = self.redis.pipeline()
        pipeline.delete(self.stats_key)
        pipeline.hset(
            self.stats_key,
            mapping={
                JobStatus.QUEUED.value: stats[JobStatus.QUEUED.value],
                JobStatus.PROCESSING.value: stats[JobStatus.PROCESSING.value],
                JobStatus.COMPLETED.value: stats[JobStatus.COMPLETED.value],
                JobStatus.FAILED.value: stats[JobStatus.FAILED.value],
                "total": stats["total"],
                "completed_duration_sum_seconds": round(completed_duration_sum, 3),
                "completed_duration_count": completed_duration_count,
                "terminal_duration_sum_seconds": round(terminal_duration_sum, 3),
                "terminal_duration_count": terminal_duration_count,
            },
        )
        pipeline.delete(self.completed_timestamps_key)
        if completed_timestamps:
            pipeline.zadd(
                self.completed_timestamps_key,
                {str(job_id): ts for job_id, ts in completed_timestamps if job_id},
            )
        pipeline.execute()

    def _job_key(self, job_id: str) -> str:
        return f"{self.job_key_prefix}{job_id}"

    def _job_index_key(self, filename: str) -> str:
        return f"{self.job_index_prefix}{filename}"

    def _get_next_job_id(self) -> str:
        job_id = self.redis.incr(self.job_counter_key)
        return f"job_{int(time.time())}_{job_id}"

    def add_job(
        self,
        url: str,
        width: int = 800,
        height: int = 450,
        selectors: Optional[str] = None,
        format: str = "webp",
        scaled_width: Optional[int] = None,
        scaled_height: Optional[int] = None,
        version: Optional[int] = None,
        timeout: Optional[int] = None,
        theme: Optional[str] = None,
        priority: int = 0,
    ) -> str:
        job_id = self._get_next_job_id()
        scaled_width = scaled_width or width
        scaled_height = scaled_height or height
        selector_list = selectors.split(",") if selectors else []
        expected_filename = build_image_name(
            url,
            selector_list,
            width,
            height,
            scaled_width,
            scaled_height,
            format,
            version,
            theme,
        )

        job_data = {
            "job_id": job_id,
            "url": url,
            "width": width,
            "height": height,
            "selectors": selectors,
            "format": format,
            "scaled_width": scaled_width,
            "scaled_height": scaled_height,
            "version": version,
            "timeout": timeout,
            "theme": theme,
            "priority": priority,
            "status": JobStatus.QUEUED.value,
            "created_at": time.time(),
            "updated_at": time.time(),
            "started_processing_at": None,
            "error": None,
            "filename": expected_filename,
        }

        score = (priority * 1_000_000_000_000) - time.time()
        self.redis.set(self._job_key(job_id), json.dumps(job_data))
        self.redis.zadd(self.queue_key, {job_id: score})
        self.redis.set(self._job_index_key(expected_filename), job_id)
        self.redis.hincrby(self.stats_key, JobStatus.QUEUED.value, 1)
        self.redis.hincrby(self.stats_key, "total", 1)

        return job_id

    def get_next_job(self) -> Optional[Dict[str, Any]]:
        result = self.redis.zpopmax(self.queue_key, 1)
        if not result:
            return None

        job_id, _score = result[0]
        job_data = self.get_job(job_id)
        if not job_data:
            return None

        if job_data["status"] != JobStatus.QUEUED.value:
            return None

        self.update_job_status(job_id, JobStatus.PROCESSING)
        return job_data

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error: Optional[str] = None,
        filename: Optional[str] = None,
    ):
        job_data = self.get_job(job_id)
        if not job_data:
            return

        previous_status = job_data.get("status")
        now = time.time()
        job_data["status"] = status.value
        job_data["updated_at"] = now
        if status == JobStatus.PROCESSING and not isinstance(
            job_data.get("started_processing_at"), (int, float)
        ):
            job_data["started_processing_at"] = now
        if error:
            job_data["error"] = error
        if filename:
            job_data["filename"] = filename

        self.redis.set(self._job_key(job_id), json.dumps(job_data))

        if previous_status != status.value:
            pipeline = self.redis.pipeline()
            if previous_status in [status.value for status in JobStatus]:
                pipeline.hincrby(self.stats_key, previous_status, -1)
            pipeline.hincrby(self.stats_key, status.value, 1)

            created_at = job_data.get("created_at")
            started_processing_at = job_data.get("started_processing_at")
            if isinstance(created_at, (int, float)) and status in [
                JobStatus.COMPLETED,
                JobStatus.FAILED,
            ]:
                duration = max(0.0, now - created_at)
                pipeline.hincrbyfloat(
                    self.stats_key,
                    "terminal_duration_sum_seconds",
                    duration,
                )
                pipeline.hincrby(self.stats_key, "terminal_duration_count", 1)
                if status == JobStatus.COMPLETED and isinstance(
                    started_processing_at, (int, float)
                ):
                    processing_duration = max(0.0, now - started_processing_at)
                    pipeline.hincrbyfloat(
                        self.stats_key,
                        "completed_duration_sum_seconds",
                        processing_duration,
                    )
                    pipeline.hincrby(self.stats_key, "completed_duration_count", 1)
                    pipeline.zadd(self.completed_timestamps_key, {job_id: now})

            pipeline.execute()

        if status == JobStatus.PROCESSING:
            self.redis.zadd(self.processing_key, {job_id: time.time()})
        if status in [JobStatus.COMPLETED, JobStatus.FAILED]:
            self.redis.zrem(self.processing_key, job_id)
            if job_data.get("filename"):
                self.redis.delete(self._job_index_key(job_data["filename"]))

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        job_data = self.redis.get(self._job_key(job_id))
        if not job_data:
            return None
        return json.loads(job_data)

    def get_job_status(self, job_id: str) -> Optional[JobStatus]:
        job_data = self.get_job(job_id)
        if job_data:
            return JobStatus(job_data["status"])
        return None

    def get_job_id_by_filename(self, filename: str) -> Optional[str]:
        return self.redis.get(self._job_index_key(filename))

    def is_shot_queued_or_processing(
        self,
        url: str,
        width: int,
        height: int,
        selectors: Optional[str] = None,
        version: Optional[int] = None,
        scaled_width: Optional[int] = None,
        scaled_height: Optional[int] = None,
        format: str = "webp",
        theme: Optional[str] = None,
    ) -> bool:
        scaled_width = scaled_width or width
        scaled_height = scaled_height or height
        selector_list = selectors.split(",") if selectors else []
        expected_filename = build_image_name(
            url,
            selector_list,
            width,
            height,
            scaled_width,
            scaled_height,
            format,
            version,
            theme,
        )

        job_id = self.redis.get(self._job_index_key(expected_filename))
        if not job_id:
            return False

        job_data = self.get_job(job_id)
        if not job_data:
            return False

        return job_data["status"] in [
            JobStatus.QUEUED.value,
            JobStatus.PROCESSING.value,
        ]

    def get_queue_stats(self) -> Dict[str, Any]:
        if not self.redis.exists(self.stats_key):
            self._rebuild_stats()

        raw = self.redis.hgetall(self.stats_key)
        now = time.time()

        queued_ids = self.redis.zrange(self.queue_key, 0, -1)
        processing_ids = self.redis.zrange(self.processing_key, 0, -1)

        queued_ages: List[float] = []
        for job_id in queued_ids:
            job_data = self.get_job(job_id)
            if job_data and isinstance(job_data.get("created_at"), (int, float)):
                queued_ages.append(max(0.0, now - job_data["created_at"]))

        processing_ages: List[float] = []
        for job_id in processing_ids:
            job_data = self.get_job(job_id)
            if job_data and isinstance(
                job_data.get("started_processing_at"), (int, float)
            ):
                processing_ages.append(
                    max(0.0, now - job_data["started_processing_at"])
                )

        self.redis.zremrangebyscore(self.completed_timestamps_key, 0, now - 3600)
        completed_last_hour = self.redis.zcard(self.completed_timestamps_key)

        completed = int(raw.get(JobStatus.COMPLETED.value, 0))
        failed = int(raw.get(JobStatus.FAILED.value, 0))
        terminal_total = completed + failed
        success_rate = (
            round((completed / terminal_total) * 100, 2) if terminal_total else 0.0
        )

        completed_duration_sum = float(raw.get("completed_duration_sum_seconds", 0.0))
        completed_duration_count = int(raw.get("completed_duration_count", 0))
        terminal_duration_sum = float(raw.get("terminal_duration_sum_seconds", 0.0))
        terminal_duration_count = int(raw.get("terminal_duration_count", 0))

        avg_processing = (
            round(completed_duration_sum / completed_duration_count, 3)
            if completed_duration_count
            else 0.0
        )
        avg_terminal = (
            round(terminal_duration_sum / terminal_duration_count, 3)
            if terminal_duration_count
            else 0.0
        )

        return {
            JobStatus.QUEUED.value: int(raw.get(JobStatus.QUEUED.value, 0)),
            JobStatus.PROCESSING.value: int(raw.get(JobStatus.PROCESSING.value, 0)),
            JobStatus.COMPLETED.value: completed,
            JobStatus.FAILED.value: failed,
            "total": int(raw.get("total", 0)),
            "avg_processing_time_seconds": avg_processing,
            "avg_terminal_time_seconds": avg_terminal,
            "queued_avg_age_seconds": _safe_avg(queued_ages),
            "queued_oldest_age_seconds": round(max(queued_ages), 3)
            if queued_ages
            else 0.0,
            "processing_avg_age_seconds": _safe_avg(processing_ages),
            "success_rate_percent": success_rate,
            "completed_last_hour": int(completed_last_hour),
        }

    def record_url_request(self, url: str, filename: str, method: str) -> None:
        """Record a request for a source URL and generated filename."""
        now = time.time()
        existing = self.redis.hget(self.url_stats_key, url)
        row = json.loads(existing) if existing else {}

        filenames = row.get("filenames", [])
        if filename not in filenames:
            filenames.append(filename)

        method_counts_raw = row.get("method_counts", {})
        method_counts = method_counts_raw if isinstance(method_counts_raw, dict) else {}
        method_counts[method] = int(method_counts.get(method, 0)) + 1

        updated = {
            "url": url,
            "request_count": int(row.get("request_count", 0)) + 1,
            "filenames": sorted(filenames),
            "first_requested_at": float(row.get("first_requested_at", now)),
            "last_requested_at": now,
            "method_counts": method_counts,
        }
        self.redis.hset(self.url_stats_key, url, json.dumps(updated))

    def get_url_stats(
        self,
        limit: Optional[int] = None,
        offset: int = 0,
        filenames_per_url: Optional[int] = None,
    ) -> Dict[str, Any]:
        """List tracked URL request counts and generated files."""
        raw = self.redis.hgetall(self.url_stats_key)
        rows = [json.loads(value) for value in raw.values()]
        return _build_url_stats(
            rows,
            limit=limit,
            offset=offset,
            filenames_per_url=filenames_per_url,
        )

    def get_active_jobs(self) -> List[Dict[str, Any]]:
        """List queued and processing jobs."""
        jobs: List[Dict[str, Any]] = []
        for key in self.redis.scan_iter(match=f"{self.job_key_prefix}*"):
            job_data = self.redis.get(key)
            if not job_data:
                continue
            jobs.append(json.loads(job_data))
        return _build_active_jobs(jobs)

    def cleanup_old_jobs(
        self,
        max_age_hours: int = 24,
        stale_age_minutes: int = 30,
        dry_run: bool = False,
    ) -> Dict[str, int]:
        cutoff_time = time.time() - (max_age_hours * 3600)
        stale_cutoff_time = time.time() - (stale_age_minutes * 60)
        removed_counts = {"completed": 0, "failed": 0, "queued": 0, "processing": 0}

        for key in self.redis.scan_iter(match=f"{self.job_key_prefix}*"):
            job_data = self.redis.get(key)
            if not job_data:
                continue
            data = json.loads(job_data)
            status = data.get("status")
            updated_at = float(data.get("updated_at", 0) or 0)
            created_at = float(data.get("created_at", 0) or 0)
            started_processing_at = float(data.get("started_processing_at", 0) or 0)

            should_remove = False
            if status in [JobStatus.COMPLETED.value, JobStatus.FAILED.value]:
                should_remove = updated_at < cutoff_time
            elif status == JobStatus.QUEUED.value:
                should_remove = created_at < stale_cutoff_time
            elif status == JobStatus.PROCESSING.value:
                marker = started_processing_at or updated_at or created_at
                should_remove = marker < stale_cutoff_time

            if not should_remove or not isinstance(status, str):
                continue

            removed_counts[status] += 1
            if dry_run:
                continue

            self.redis.delete(key)
            job_id = data.get("job_id")
            if job_id:
                self.redis.zrem(self.queue_key, job_id)
                self.redis.zrem(self.processing_key, job_id)
            if data.get("filename"):
                self.redis.delete(self._job_index_key(data["filename"]))

        if not dry_run:
            self._rebuild_stats()

        return removed_counts

    def record_worker_heartbeat(
        self, worker_id: str, timestamp: Optional[float] = None
    ) -> None:
        heartbeat_time = float(timestamp if timestamp is not None else time.time())
        self.redis.hset(self.worker_heartbeats_key, worker_id, heartbeat_time)

    def get_worker_heartbeat(self, worker_id: str) -> Optional[float]:
        value = self.redis.hget(self.worker_heartbeats_key, worker_id)
        return float(value) if value is not None else None


# Global queue instance
_queue: Optional[QueueBase] = None


def get_queue() -> QueueBase:
    """Get the global queue instance"""
    global _queue
    if _queue is None:
        queue_backend = (config.queue_backend or "auto").lower()
        if queue_backend == "redis" or (queue_backend == "auto" and config.redis_url):
            redis_url = config.redis_url
            if not redis_url:
                raise RuntimeError("REDIS_URL must be set when using redis queue")
            _queue = RedisQueue(
                redis_url=redis_url,
                namespace=config.queue_namespace or "shot-scraper",
            )
        else:
            cache_dir = (
                config.cache_dir
                if config.env == "prod" and config.cache_dir
                else "/tmp/shot-scraper-queue"
            )
            _queue = ScreenshotQueue(cache_dir=cache_dir)
    return _queue
