"""
Crawl management API endpoints
"""

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel, HttpUrl
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid

router = APIRouter()


class CrawlTarget(BaseModel):
    """Crawl target model"""
    domain: str
    target_type: str = "news"  # news, forum, blog, social
    priority: int = 50
    crawl_frequency_minutes: int = 60
    crawl_depth: int = 2
    respect_robots: bool = True
    rate_limit_rpm: int = 60
    metadata: Optional[Dict[str, Any]] = None


class ManualCrawlRequest(BaseModel):
    """Manual crawl request"""
    url: HttpUrl
    depth: int = 2
    priority: int = 50


@router.post("/targets")
async def create_crawl_target(
    target: CrawlTarget,
    request: Request
) -> Dict[str, Any]:
    """
    Create a new crawl target
    """
    db = request.app.state.db
    
    # Check if target already exists
    existing = await db.pg_fetchrow(
        "SELECT id FROM crawl_targets WHERE domain = $1",
        target.domain
    )
    
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Target already exists: {target.domain}"
        )
    
    # Insert new target
    target_id = await db.pg_fetchval(
        """
        INSERT INTO crawl_targets (
            domain, target_type, priority, crawl_frequency,
            crawl_depth, respect_robots, rate_limit_rpm, metadata
        ) VALUES ($1, $2, $3, $4 * INTERVAL '1 minute', $5, $6, $7, $8)
        RETURNING id
        """,
        target.domain,
        target.target_type,
        target.priority,
        target.crawl_frequency_minutes,
        target.crawl_depth,
        target.respect_robots,
        target.rate_limit_rpm,
        target.metadata
    )
    
    # Log audit event
    await db.pg_execute(
        """
        INSERT INTO audit_log (event_type, actor, action, resource_type, resource_id)
        VALUES ($1, $2, $3, $4, $5)
        """,
        "target_created",
        "api_user",
        f"Created crawl target: {target.domain}",
        "crawl_target",
        target_id
    )
    
    return {
        "id": str(target_id),
        "domain": target.domain,
        "status": "created",
        "message": "Crawl target created successfully"
    }


@router.get("/targets")
async def list_crawl_targets(
    request: Request,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """
    List all crawl targets
    """
    db = request.app.state.db
    
    # Build query
    query = "SELECT * FROM crawl_targets"
    params = []
    
    if status:
        query += " WHERE status = $1"
        params.append(status)
    
    query += " ORDER BY priority DESC, created_at DESC LIMIT $2 OFFSET $3"
    params.extend([limit, offset])
    
    # Get targets
    targets = await db.pg_fetch(query, *params)
    
    # Get total count
    count_query = "SELECT COUNT(*) FROM crawl_targets"
    if status:
        count_query += " WHERE status = $1"
        total = await db.pg_fetchval(count_query, status) if status else await db.pg_fetchval(count_query)
    else:
        total = await db.pg_fetchval(count_query)
    
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "targets": targets
    }


@router.get("/targets/{target_id}")
async def get_crawl_target(
    target_id: str,
    request: Request
) -> Dict[str, Any]:
    """
    Get specific crawl target details
    """
    db = request.app.state.db
    
    target = await db.pg_fetchrow(
        "SELECT * FROM crawl_targets WHERE id = $1",
        uuid.UUID(target_id)
    )
    
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    
    # Get recent jobs for this target
    jobs = await db.pg_fetch(
        """
        SELECT * FROM crawl_jobs
        WHERE target_id = $1
        ORDER BY created_at DESC
        LIMIT 10
        """,
        uuid.UUID(target_id)
    )
    
    return {
        "target": target,
        "recent_jobs": jobs
    }


@router.post("/targets/{target_id}/trigger")
async def trigger_manual_crawl(
    target_id: str,
    request: Request,
    background_tasks: BackgroundTasks
) -> Dict[str, Any]:
    """
    Manually trigger a crawl for a target
    """
    db = request.app.state.db
    queue = request.app.state.queue
    
    # Get target
    target = await db.pg_fetchrow(
        "SELECT * FROM crawl_targets WHERE id = $1 AND status = 'active'",
        uuid.UUID(target_id)
    )
    
    if not target:
        raise HTTPException(status_code=404, detail="Active target not found")
    
    # Create job
    job_id = await db.pg_fetchval(
        """
        INSERT INTO crawl_jobs (target_id, job_type, status)
        VALUES ($1, 'manual', 'pending')
        RETURNING id
        """,
        uuid.UUID(target_id)
    )
    
    # Publish to queue
    await queue.publish_crawl_request({
        "job_id": str(job_id),
        "target_id": str(target_id),
        "domain": target["domain"],
        "depth": target["crawl_depth"],
        "priority": target["priority"]
    })
    
    return {
        "job_id": str(job_id),
        "status": "queued",
        "message": f"Crawl job queued for {target['domain']}"
    }


@router.delete("/targets/{target_id}")
async def delete_crawl_target(
    target_id: str,
    request: Request
) -> Dict[str, Any]:
    """
    Delete a crawl target (actually archives it)
    """
    db = request.app.state.db
    
    # Archive instead of delete
    result = await db.pg_execute(
        "UPDATE crawl_targets SET status = 'archived', updated_at = NOW() WHERE id = $1",
        uuid.UUID(target_id)
    )
    
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Target not found")
    
    return {
        "id": target_id,
        "status": "archived",
        "message": "Target archived successfully"
    }


@router.get("/jobs")
async def list_crawl_jobs(
    request: Request,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """
    List crawl jobs
    """
    db = request.app.state.db
    
    query = """
        SELECT 
            cj.*,
            ct.domain,
            ct.target_type
        FROM crawl_jobs cj
        JOIN crawl_targets ct ON cj.target_id = ct.id
    """
    params = []
    
    if status:
        query += " WHERE cj.status = $1"
        params.append(status)
    
    query += " ORDER BY cj.created_at DESC LIMIT $2 OFFSET $3"
    params.extend([limit, offset])
    
    jobs = await db.pg_fetch(query, *params)
    
    # Get total
    count_query = "SELECT COUNT(*) FROM crawl_jobs"
    if status:
        count_query += " WHERE status = $1"
        total = await db.pg_fetchval(count_query, status) if status else await db.pg_fetchval(count_query)
    else:
        total = await db.pg_fetchval(count_query)
    
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "jobs": jobs
    }


@router.get("/jobs/{job_id}")
async def get_crawl_job(
    job_id: str,
    request: Request
) -> Dict[str, Any]:
    """
    Get specific job details
    """
    db = request.app.state.db
    
    job = await db.pg_fetchrow(
        """
        SELECT 
            cj.*,
            ct.domain,
            ct.target_type
        FROM crawl_jobs cj
        JOIN crawl_targets ct ON cj.target_id = ct.id
        WHERE cj.id = $1
        """,
        uuid.UUID(job_id)
    )
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Get artifacts created by this job
    artifacts = await db.pg_fetch(
        "SELECT * FROM artifacts WHERE job_id = $1 ORDER BY created_at DESC",
        uuid.UUID(job_id)
    )
    
    return {
        "job": job,
        "artifacts": artifacts
    }


@router.get("/stats")
async def get_crawl_stats(request: Request) -> Dict[str, Any]:
    """
    Get crawling statistics
    """
    db = request.app.state.db
    queue = request.app.state.queue
    
    # Get job stats
    job_stats = await db.pg_fetch(
        """
        SELECT 
            status,
            COUNT(*) as count,
            SUM(pages_crawled) as total_pages,
            SUM(artifacts_collected) as total_artifacts
        FROM crawl_jobs
        WHERE created_at > NOW() - INTERVAL '24 hours'
        GROUP BY status
        """
    )
    
    # Get target stats
    target_stats = await db.pg_fetchrow(
        """
        SELECT 
            COUNT(*) as total_targets,
            COUNT(*) FILTER (WHERE status = 'active') as active_targets,
            COUNT(*) FILTER (WHERE status = 'paused') as paused_targets
        FROM crawl_targets
        """
    )
    
    # Get queue stats
    queue_stats = await queue.get_all_queue_stats()
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "jobs_24h": job_stats,
        "targets": target_stats,
        "queues": queue_stats
    }