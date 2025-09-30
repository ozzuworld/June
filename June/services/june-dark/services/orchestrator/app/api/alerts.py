"""
Alerts management API endpoints
"""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid

router = APIRouter()


class Watchlist(BaseModel):
    """Watchlist model"""
    name: str
    watchlist_type: str  # domain, keyword, email, phone, face, pattern
    pattern: str
    is_regex: bool = False
    priority: str = "medium"  # low, medium, high, critical
    metadata: Optional[Dict[str, Any]] = None


@router.post("/watchlists")
async def create_watchlist(
    watchlist: Watchlist,
    request: Request
) -> Dict[str, Any]:
    """
    Create a new watchlist
    """
    db = request.app.state.db
    
    watchlist_id = await db.pg_fetchval(
        """
        INSERT INTO watchlists (name, watchlist_type, pattern, is_regex, priority, metadata)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        watchlist.name,
        watchlist.watchlist_type,
        watchlist.pattern,
        watchlist.is_regex,
        watchlist.priority,
        watchlist.metadata
    )
    
    return {
        "id": str(watchlist_id),
        "name": watchlist.name,
        "status": "created"
    }


@router.get("/watchlists")
async def list_watchlists(
    request: Request,
    watchlist_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    List all watchlists
    """
    db = request.app.state.db
    
    query = "SELECT * FROM watchlists"
    params = []
    
    if watchlist_type:
        query += " WHERE watchlist_type = $1"
        params.append(watchlist_type)
    
    query += " ORDER BY priority DESC, created_at DESC"
    
    watchlists = await db.pg_fetch(query, *params)
    
    return {
        "total": len(watchlists),
        "watchlists": watchlists
    }


@router.get("/")
async def list_alerts(
    request: Request,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """
    List alerts with filtering
    """
    db = request.app.state.db
    
    query = "SELECT * FROM alerts"
    where_clauses = []
    params = []
    param_count = 1
    
    if severity:
        where_clauses.append(f"severity = ${param_count}")
        params.append(severity)
        param_count += 1
    
    if status:
        where_clauses.append(f"status = ${param_count}")
        params.append(status)
        param_count += 1
    
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    
    query += f" ORDER BY created_at DESC LIMIT ${param_count} OFFSET ${param_count + 1}"
    params.extend([limit, offset])
    
    alerts = await db.pg_fetch(query, *params)
    
    # Get total count
    count_query = "SELECT COUNT(*) FROM alerts"
    if where_clauses:
        count_query += " WHERE " + " AND ".join(where_clauses)
    
    total = await db.pg_fetchval(count_query, *params[:-2]) if where_clauses else await db.pg_fetchval(count_query)
    
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "alerts": alerts
    }


@router.get("/{alert_id}")
async def get_alert(
    alert_id: str,
    request: Request
) -> Dict[str, Any]:
    """
    Get specific alert details
    """
    db = request.app.state.db
    
    alert = await db.pg_fetchrow(
        """
        SELECT 
            a.*,
            w.name as watchlist_name,
            w.watchlist_type,
            ar.source_url,
            ar.artifact_type
        FROM alerts a
        LEFT JOIN watchlists w ON a.watchlist_id = w.id
        LEFT JOIN artifacts ar ON a.artifact_id = ar.id
        WHERE a.id = $1
        """,
        uuid.UUID(alert_id)
    )
    
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    return alert


@router.patch("/{alert_id}/status")
async def update_alert_status(
    alert_id: str,
    request: Request,
    status: str,
    assigned_to: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update alert status
    """
    db = request.app.state.db
    
    valid_statuses = ["new", "acknowledged", "investigating", "resolved", "false_positive"]
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
    
    query = "UPDATE alerts SET status = $1, updated_at = NOW()"
    params = [status]
    param_count = 2
    
    if assigned_to:
        query += f", assigned_to = ${param_count}"
        params.append(assigned_to)
        param_count += 1
    
    if status == "resolved":
        query += f", resolved_at = NOW()"
    
    query += f" WHERE id = ${param_count} RETURNING *"
    params.append(uuid.UUID(alert_id))
    
    result = await db.pg_fetchrow(query, *params)
    
    if not result:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    return result


@router.get("/stats/summary")
async def get_alert_stats(request: Request) -> Dict[str, Any]:
    """
    Get alert statistics
    """
    db = request.app.state.db
    
    # Get stats by severity
    severity_stats = await db.pg_fetch(
        """
        SELECT 
            severity,
            COUNT(*) as count,
            COUNT(*) FILTER (WHERE status = 'new') as new_count,
            COUNT(*) FILTER (WHERE status = 'resolved') as resolved_count
        FROM alerts
        WHERE created_at > NOW() - INTERVAL '7 days'
        GROUP BY severity
        ORDER BY 
            CASE severity
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                WHEN 'low' THEN 4
            END
        """
    )
    
    # Get stats by type
    type_stats = await db.pg_fetch(
        """
        SELECT 
            alert_type,
            COUNT(*) as count
        FROM alerts
        WHERE created_at > NOW() - INTERVAL '7 days'
        GROUP BY alert_type
        ORDER BY count DESC
        """
    )
    
    # Get recent critical/high alerts
    recent_important = await db.pg_fetch(
        """
        SELECT * FROM alerts
        WHERE severity IN ('critical', 'high')
        AND status IN ('new', 'acknowledged')
        ORDER BY created_at DESC
        LIMIT 10
        """
    )
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "by_severity": severity_stats,
        "by_type": type_stats,
        "recent_important": recent_important
    }