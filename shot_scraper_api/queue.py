import enum
import json
import time
from typing import Optional, Dict, Any

import diskcache
from redis import Redis

from shot_scraper_api.config import config
from shot_scraper_api.screenshot import build_image_name


class JobStatus(enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


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
    ) -> bool:
        raise NotImplementedError

    def get_queue_stats(self) -> Dict[str, int]:
        raise NotImplementedError

    def cleanup_old_jobs(self, max_age_hours: int = 24):
        raise NotImplementedError


class ScreenshotQueue(QueueBase):
    def __init__(self, cache_dir: str = "/tmp/shot-scraper-queue"):
        self.cache = diskcache.Cache(cache_dir)
        self.job_counter_key = "job_counter"
        self.job_index_key = "job_by_filename"

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
        priority: int = 0,
    ) -> str:
        """Add a screenshot job to the queue"""
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
            "priority": priority,
            "status": JobStatus.QUEUED.value,
            "created_at": time.time(),
            "updated_at": time.time(),
            "error": None,
            "filename": expected_filename,
        }

        # Store job data
        self.cache.set(f"job:{job_id}", job_data)

        # Store filename index
        filename_index_raw = self.cache.get(self.job_index_key)
        filename_index = (
            filename_index_raw if isinstance(filename_index_raw, dict) else {}
        )
        filename_index[expected_filename] = job_id
        self.cache.set(self.job_index_key, filename_index)

        # Add to priority queue
        queue_key = f"queue:priority:{priority}"
        existing_jobs_raw = self.cache.get(queue_key)
        existing_jobs = existing_jobs_raw if isinstance(existing_jobs_raw, list) else []
        existing_jobs.append(job_id)
        self.cache.set(queue_key, existing_jobs)

        return job_id

    def get_next_job(self) -> Optional[Dict[str, Any]]:
        """Get the next job from the queue"""
        # Try to get from highest priority queue first
        for priority in range(10, -1, -1):  # Check priorities 10 to 0
            queue_key = f"queue:priority:{priority}"
            job_ids_raw = self.cache.get(queue_key)
            job_ids = job_ids_raw if isinstance(job_ids_raw, list) else []

            if job_ids:
                job_id = str(job_ids[0])
                job_data = self.get_job(job_id)

                if job_data and job_data["status"] == JobStatus.QUEUED.value:
                    # Remove from this priority queue
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
            job_data["updated_at"] = time.time()
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

    def get_queue_stats(self) -> Dict[str, int]:
        """Get queue statistics"""
        stats = {status.value: 0 for status in JobStatus}
        stats["total"] = 0

        for key in list(self.cache.iterkeys()):
            if isinstance(key, str) and key.startswith("job:"):
                job_data = self.cache.get(key)
                if job_data and isinstance(job_data, dict):
                    status = job_data.get("status")
                    if status in stats:
                        stats[status] += 1
                    stats["total"] += 1

        return stats

    def cleanup_old_jobs(self, max_age_hours: int = 24):
        """Clean up old completed/failed jobs"""
        cutoff_time = time.time() - (max_age_hours * 3600)

        for key in list(self.cache.iterkeys()):
            if isinstance(key, str) and key.startswith("job:"):
                job_data = self.cache.get(key)
                if (
                    job_data
                    and isinstance(job_data, dict)
                    and job_data["status"]
                    in [JobStatus.COMPLETED.value, JobStatus.FAILED.value]
                ):
                    if job_data["updated_at"] < cutoff_time:
                        self.cache.delete(key)
                        filename_index_raw = self.cache.get(self.job_index_key)
                        filename_index = (
                            filename_index_raw
                            if isinstance(filename_index_raw, dict)
                            else {}
                        )
                        if job_data.get("filename") in filename_index:
                            del filename_index[job_data["filename"]]
                            self.cache.set(self.job_index_key, filename_index)


class RedisQueue(QueueBase):
    def __init__(self, redis_url: str, namespace: str = "shot-scraper"):
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.namespace = namespace
        self.job_counter_key = f"{namespace}:job_counter"
        self.queue_key = f"{namespace}:queue"
        self.processing_key = f"{namespace}:processing"
        self.job_key_prefix = f"{namespace}:job:"
        self.job_index_prefix = f"{namespace}:job_by_filename:"

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
            "priority": priority,
            "status": JobStatus.QUEUED.value,
            "created_at": time.time(),
            "updated_at": time.time(),
            "error": None,
            "filename": expected_filename,
        }

        score = (priority * 1_000_000_000_000) - time.time()
        self.redis.set(self._job_key(job_id), json.dumps(job_data))
        self.redis.zadd(self.queue_key, {job_id: score})
        self.redis.set(self._job_index_key(expected_filename), job_id)

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

        job_data["status"] = status.value
        job_data["updated_at"] = time.time()
        if error:
            job_data["error"] = error
        if filename:
            job_data["filename"] = filename

        self.redis.set(self._job_key(job_id), json.dumps(job_data))

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

    def get_queue_stats(self) -> Dict[str, int]:
        stats = {status.value: 0 for status in JobStatus}
        stats["total"] = 0

        for key in self.redis.scan_iter(match=f"{self.job_key_prefix}*"):
            job_data = self.redis.get(key)
            if not job_data:
                continue
            data = json.loads(job_data)
            status = data.get("status")
            if status in stats:
                stats[status] += 1
            stats["total"] += 1

        return stats

    def cleanup_old_jobs(self, max_age_hours: int = 24):
        cutoff_time = time.time() - (max_age_hours * 3600)

        for key in self.redis.scan_iter(match=f"{self.job_key_prefix}*"):
            job_data = self.redis.get(key)
            if not job_data:
                continue
            data = json.loads(job_data)
            if data.get("status") in [
                JobStatus.COMPLETED.value,
                JobStatus.FAILED.value,
            ]:
                if data.get("updated_at", 0) < cutoff_time:
                    self.redis.delete(key)
                    if data.get("filename"):
                        self.redis.delete(self._job_index_key(data["filename"]))


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
