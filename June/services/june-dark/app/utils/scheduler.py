"""
Task Scheduler for automated crawling
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
import schedule
import threading

logger = logging.getLogger(__name__)


class TaskScheduler:
    """Manages scheduled tasks for crawling"""
    
    def __init__(self, db_manager, queue_manager):
        self.db = db_manager
        self.queue = queue_manager
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
    
    def start(self):
        """Start the scheduler"""
        if self.running:
            logger.warning("Scheduler already running")
            return
        
        self.running = True
        
        # Schedule tasks
        schedule.every(1).minutes.do(self._schedule_wrapper, self.check_pending_crawls)
        schedule.every(5).minutes.do(self._schedule_wrapper, self.cleanup_stale_jobs)
        schedule.every(1).hours.do(self._schedule_wrapper, self.update_queue_metrics)
        
        # Start scheduler thread
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        
        logger.info("✓ Task scheduler started")
    
    def stop(self):
        """Stop the scheduler"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("✓ Task scheduler stopped")
    
    def _run_scheduler(self):
        """Run scheduler in background thread"""
        while self.running:
            schedule.run_pending()
            threading.Event().wait(1)
    
    def _schedule_wrapper(self, coro_func):
        """Wrapper to run async functions in scheduler"""
        def wrapper():
            if not self.loop:
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(coro_func())
        return wrapper
    
    async def check_pending_crawls(self):
        """Check for targets that need crawling"""
        try:
            # Get targets due for crawling
            targets = await self.db.pg_fetch(
                """
                SELECT * FROM crawl_targets
                WHERE status = 'active'
                AND (next_crawl_at IS NULL OR next_crawl_at <= NOW())
                ORDER BY priority DESC
                LIMIT 50
                """
            )
            
            for target in targets:
                # Create job
                job_id = await self.db.pg_fetchval(
                    """
                    INSERT INTO crawl_jobs (target_id, job_type, status)
                    VALUES ($1, 'scheduled', 'pending')
                    RETURNING id
                    """,
                    target["id"]
                )
                
                # Publish to queue
                await self.queue.publish_crawl_request({
                    "job_id": str(job_id),
                    "target_id": str(target["id"]),
                    "domain": target["domain"],
                    "depth": target["crawl_depth"],
                    "priority": target["priority"]
                })
                
                # Update next crawl time
                await self.db.pg_execute(
                    """
                    UPDATE crawl_targets
                    SET next_crawl_at = NOW() + crawl_frequency,
                        last_crawled_at = NOW()
                    WHERE id = $1
                    """,
                    target["id"]
                )
                
                logger.info(f"Scheduled crawl for {target['domain']}")
        
        except Exception as e:
            logger.error(f"Error checking pending crawls: {e}")
    
    async def cleanup_stale_jobs(self):
        """Mark stale jobs as failed"""
        try:
            # Jobs running for more than 2 hours
            await self.db.pg_execute(
                """
                UPDATE crawl_jobs
                SET status = 'failed',
                    error_message = 'Job timeout - exceeded 2 hours',
                    completed_at = NOW()
                WHERE status = 'running'
                AND started_at < NOW() - INTERVAL '2 hours'
                """
            )
            
            logger.debug("Cleaned up stale jobs")
        
        except Exception as e:
            logger.error(f"Error cleaning up stale jobs: {e}")
    
    async def update_queue_metrics(self):
        """Update queue metrics in database"""
        try:
            queue_stats = await self.queue.get_all_queue_stats()
            
            for queue_name, stats in queue_stats.items():
                if "error" not in stats:
                    await self.db.pg_execute(
                        """
                        INSERT INTO queue_metrics (
                            queue_name, messages_pending, recorded_at
                        ) VALUES ($1, $2, NOW())
                        """,
                        queue_name,
                        stats.get("messages", 0)
                    )
            
            logger.debug("Updated queue metrics")
        
        except Exception as e:
            logger.error(f"Error updating queue metrics: {e}")