import asyncio
import logging
from typing import Optional

from shot_scraper_api.screenshot import generate_image_data
from shot_scraper_api.config import config
from shot_scraper_api.console import console
from shot_scraper_api.queue import get_queue, JobStatus


class QueueProcessor:
    def __init__(self, poll_interval: float = 1.0):
        self.poll_interval = poll_interval
        self.running = False
        self.task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the background queue processor"""
        if self.running:
            return

        self.running = True
        self.task = asyncio.create_task(self._process_queue())
        console.log("Queue processor started")

    async def stop(self):
        """Stop the background queue processor"""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        console.log("Queue processor stopped")

    async def _process_queue(self):
        """Main queue processing loop"""
        queue = get_queue()

        while self.running:
            try:
                # Get next job
                job = queue.get_next_job()

                if job:
                    await self._process_job(queue, job)
                else:
                    # No jobs, wait before next check
                    await asyncio.sleep(self.poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                console.log(f"Queue processor error: {e}")
                await asyncio.sleep(self.poll_interval)

    async def _process_job(self, queue, job):
        """Process a single screenshot job"""
        job_id = job["job_id"]

        try:
            # Mark as processing
            queue.update_job_status(job_id, JobStatus.PROCESSING)
            console.log(f"Processing job {job_id} for {job['url']}")

            # Generate the screenshot
            imgname, output_path, existed_in_s3 = await generate_image_data(
                url=job["url"],
                width=job["width"],
                height=job["height"],
                selector_list=job["selectors"].split(",") if job["selectors"] else [],
                format=job["format"],
                scaled_width=job["scaled_width"],
                scaled_height=job["scaled_height"],
                version=job["version"],
                timeout_ms=job["timeout"],
            )

            # Mark as completed
            queue.update_job_status(job_id, JobStatus.COMPLETED, filename=imgname)
            console.log(f"Completed job {job_id}: {imgname}")

        except Exception as e:
            # Mark as failed
            error_msg = str(e)
            queue.update_job_status(job_id, JobStatus.FAILED, error=error_msg)
            console.log(f"Failed job {job_id}: {error_msg}")


# Global processor instance
_processor: Optional[QueueProcessor] = None


def get_processor() -> QueueProcessor:
    """Get the global queue processor instance"""
    global _processor
    if _processor is None:
        _processor = QueueProcessor()
    return _processor


async def start_queue_processor():
    """Start the queue processor (called from FastAPI startup)"""
    processor = get_processor()
    await processor.start()


async def stop_queue_processor():
    """Stop the queue processor (called from FastAPI shutdown)"""
    processor = get_processor()
    await processor.stop()
