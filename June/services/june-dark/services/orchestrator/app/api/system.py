"""
System management API endpoints
"""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime

router = APIRouter()


class SystemConfig(BaseModel):
    """System configuration update"""
    key: str
    value: Any
    description: Optional[str] = None


@router.get("/config")
async def get_system_config(request: Request) -> Dict[str, Any]:
    """
    Get all system configuration
    """
    db = request.app.state.db
    
    config = await db.pg_fetch("SELECT * FROM system_config ORDER BY key")
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "config": {row["key"]: row["value"] for row in config}
    }


@router.get("/config/{key}")
async def get_config_value(
    key: str,
    request: Request
) -> Dict[str, Any]:
    """
    Get specific configuration value
    """
    db = request.app.state.db
    
    result = await db.pg_fetchrow(
        "SELECT * FROM system_config WHERE key = $1",
        key
    )
    
    if not result:
        raise HTTPException(status_code=404, detail=f"Config key not found: {key}")
    
    return result


@router.post("/config")
async def update_system_config(
    config: SystemConfig,
    request: Request
) -> Dict[str, Any]:
    """
    Update system configuration
    """
    db = request.app.state.db
    
    # Upsert configuration
    await db.pg_execute(
        """
        INSERT INTO system_config (key, value, description)
        VALUES ($1, $2, $3)
        ON CONFLICT (key) DO UPDATE
        SET value = $2, description = $3, updated_at = NOW()
        """,
        config.key,
        config.value,
        config.description
    )
    
    # Log audit event
    await db.pg_execute(
        """
        INSERT INTO audit_log (event_type, actor, action, metadata)
        VALUES ($1, $2, $3, $4)
        """,
        "config_changed",
        "api_user",
        f"Updated config: {config.key}",
        {"key": config.key, "value": config.value}
    )
    
    return {
        "key": config.key,
        "value": config.value,
        "status": "updated"
    }


@router.post("/mode/{mode}")
async def switch_operational_mode(
    mode: str,
    request: Request
) -> Dict[str, Any]:
    """
    Switch between day and night modes
    """
    if mode not in ["day", "night"]:
        raise HTTPException(status_code=400, detail="Mode must be 'day' or 'night'")
    
    db = request.app.state.db
    
    # Update mode in database
    await db.pg_execute(
        """
        UPDATE system_config
        SET value = $1, updated_at = NOW()
        WHERE key = 'mode'
        """,
        f'"{mode}"'
    )
    
    # Update concurrency settings based on mode
    if mode == "night":
        concurrency = 32
        delay = 0.3
    else:
        concurrency = 8
        delay = 1.0
    
    await db.pg_execute(
        """
        UPDATE system_config
        SET value = $1, updated_at = NOW()
        WHERE key = 'collector_concurrency'
        """,
        concurrency
    )
    
    await db.pg_execute(
        """
        UPDATE system_config
        SET value = $1, updated_at = NOW()
        WHERE key = 'collector_delay'
        """,
        delay
    )
    
    # Log the change
    await db.pg_execute(
        """
        INSERT INTO audit_log (event_type, actor, action, metadata)
        VALUES ($1, $2, $3, $4)
        """,
        "mode_switched",
        "api_user",
        f"Switched to {mode} mode",
        {"mode": mode, "concurrency": concurrency, "delay": delay}
    )
    
    return {
        "mode": mode,
        "concurrency": concurrency,
        "delay": delay,
        "status": "switched",
        "message": f"System switched to {mode} mode. Restart collectors for changes to take effect."
    }


@router.get("/stats")
async def get_system_stats(request: Request) -> Dict[str, Any]:
    """
    Get comprehensive system statistics
    """
    db = request.app.state.db
    queue = request.app.state.queue
    storage = request.app.state.storage
    
    # Database stats
    db_stats = await db.pg_fetchrow(
        """
        SELECT 
            (SELECT COUNT(*) FROM crawl_targets WHERE status = 'active') as active_targets,
            (SELECT COUNT(*) FROM crawl_jobs WHERE created_at > NOW() - INTERVAL '24 hours') as jobs_24h,
            (SELECT COUNT(*) FROM artifacts) as total_artifacts,
            (SELECT COUNT(*) FROM alerts WHERE status = 'new') as new_alerts
        """
    )
    
    # Queue stats
    queue_stats = await queue.get_all_queue_stats()
    
    # Storage stats
    try:
        storage_stats = storage.get_bucket_stats("june-artifacts")
    except Exception as e:
        storage_stats = {"error": str(e)}
    
    # Neo4j node counts
    try:
        neo4j_stats = await db.neo4j_run(
            """
            MATCH (n)
            WITH labels(n) as labels
            UNWIND labels as label
            RETURN label, count(*) as count
            ORDER BY count DESC
            """
        )
    except Exception:
        neo4j_stats = []
    
    # Elasticsearch index stats
    try:
        es_indices = await db.es_client.cat.indices(format="json")
        es_stats = [
            {
                "index": idx["index"],
                "docs_count": idx.get("docs.count", "0"),
                "store_size": idx.get("store.size", "0")
            }
            for idx in es_indices
            if idx["index"].startswith("june-")
        ]
    except Exception:
        es_stats = []
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "database": db_stats,
        "queues": queue_stats,
        "storage": storage_stats,
        "neo4j_nodes": neo4j_stats,
        "elasticsearch_indices": es_stats
    }


@router.get("/audit")
async def get_audit_log(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    event_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get audit log entries
    """
    db = request.app.state.db
    
    query = "SELECT * FROM audit_log"
    params = []
    
    if event_type:
        query += " WHERE event_type = $1"
        params.append(event_type)
    
    query += f" ORDER BY created_at DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
    params.extend([limit, offset])
    
    logs = await db.pg_fetch(query, *params)
    
    return {
        "total": len(logs),
        "limit": limit,
        "offset": offset,
        "logs": logs
    }