"""
Metrics Collection for June Orchestrator
Phase 1 Implementation

Provides comprehensive metrics tracking for:
- Latency monitoring
- Quality assessment
- Conversation analytics
- User experience metrics
"""
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ConversationMetrics:
    """
    Comprehensive conversation metrics
    
    Tracks all important metrics for a single conversation turn
    """
    # Identifiers
    session_id: str
    turn_number: int
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Latency metrics (milliseconds)
    first_token_latency_ms: float = 0.0
    total_response_time_ms: float = 0.0
    stt_latency_ms: float = 0.0
    llm_latency_ms: float = 0.0
    tts_latency_ms: float = 0.0
    intent_classification_ms: float = 0.0
    
    # Quality metrics
    transcription_confidence: float = 0.0
    intent_confidence: float = 0.0
    response_relevance_score: float = 0.0
    
    # Conversation metrics
    user_message_length: int = 0
    assistant_message_length: int = 0
    sentences_sent: int = 0
    tools_used: List[str] = field(default_factory=list)
    
    # User experience
    was_interrupted: bool = False
    clarification_needed: bool = False
    error_occurred: bool = False
    error_type: Optional[str] = None
    
    # Context
    intent_name: Optional[str] = None
    dialogue_state: Optional[str] = None
    context_switches: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data
    
    def get_summary(self) -> str:
        """Get human-readable summary"""
        return (
            f"Turn {self.turn_number}: "
            f"Total={self.total_response_time_ms:.0f}ms, "
            f"Intent={self.intent_name}({self.intent_confidence:.2f}), "
            f"Sentences={self.sentences_sent}"
        )


class MetricsCollector:
    """
    Collect and aggregate conversation metrics
    
    Provides:
    - Real-time metrics recording
    - Aggregated statistics
    - Performance analytics
    - Export capabilities
    """
    
    def __init__(self, buffer_size: int = 1000):
        self.buffer_size = buffer_size
        self.metrics_buffer: List[ConversationMetrics] = []
        self.session_metrics: Dict[str, List[ConversationMetrics]] = defaultdict(list)
        
        # Aggregated stats
        self.total_conversations = 0
        self.total_errors = 0
        self.total_interruptions = 0
        self.latency_samples: List[float] = []
        
        logger.info(f"✅ MetricsCollector initialized (buffer_size={buffer_size})")
    
    def record_conversation(self, metrics: ConversationMetrics):
        """
        Record conversation metrics
        
        Args:
            metrics: ConversationMetrics object
        """
        # Add to buffer
        self.metrics_buffer.append(metrics)
        
        # Add to session-specific metrics
        self.session_metrics[metrics.session_id].append(metrics)
        
        # Update aggregated stats
        self.total_conversations += 1
        if metrics.error_occurred:
            self.total_errors += 1
        if metrics.was_interrupted:
            self.total_interruptions += 1
        
        self.latency_samples.append(metrics.total_response_time_ms)
        
        # Trim buffer if too large
        if len(self.metrics_buffer) > self.buffer_size:
            self.metrics_buffer = self.metrics_buffer[-self.buffer_size:]
        
        # Trim latency samples
        if len(self.latency_samples) > 1000:
            self.latency_samples = self.latency_samples[-1000:]
        
        # Log important metrics
        if metrics.error_occurred:
            logger.error(f"❌ Error in conversation: {metrics.error_type}")
        
        if metrics.total_response_time_ms > 5000:  # >5 seconds
            logger.warning(
                f"⚠️ Slow response: {metrics.total_response_time_ms:.0f}ms "
                f"for session {metrics.session_id[:8]}..."
            )
    
    def start_timer(self) -> float:
        """
        Start a timer for latency tracking
        
        Returns:
            Start time in seconds
        """
        return time.time()
    
    def measure_latency(self, start_time: float) -> float:
        """
        Measure latency from start time
        
        Args:
            start_time: Start time from start_timer()
            
        Returns:
            Latency in milliseconds
        """
        return (time.time() - start_time) * 1000
    
    def get_session_metrics(self, session_id: str) -> List[ConversationMetrics]:
        """Get all metrics for a specific session"""
        return self.session_metrics.get(session_id, [])
    
    def get_aggregated_stats(
        self, 
        time_window_minutes: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get aggregated statistics
        
        Args:
            time_window_minutes: Only include metrics from last N minutes
                                If None, include all metrics
        
        Returns:
            Dictionary of aggregated statistics
        """
        # Filter by time window if specified
        if time_window_minutes:
            cutoff_time = datetime.utcnow() - timedelta(minutes=time_window_minutes)
            metrics = [
                m for m in self.metrics_buffer
                if m.timestamp >= cutoff_time
            ]
        else:
            metrics = self.metrics_buffer
        
        if not metrics:
            return self._empty_stats()
        
        # Calculate statistics
        total_count = len(metrics)
        error_count = sum(1 for m in metrics if m.error_occurred)
        interrupt_count = sum(1 for m in metrics if m.was_interrupted)
        
        # Latency statistics
        latencies = [m.total_response_time_ms for m in metrics]
        avg_latency = sum(latencies) / len(latencies)
        min_latency = min(latencies)
        max_latency = max(latencies)
        
        # P95 and P99 latency
        sorted_latencies = sorted(latencies)
        p95_idx = int(len(sorted_latencies) * 0.95)
        p99_idx = int(len(sorted_latencies) * 0.99)
        p95_latency = sorted_latencies[p95_idx] if p95_idx < len(sorted_latencies) else max_latency
        p99_latency = sorted_latencies[p99_idx] if p99_idx < len(sorted_latencies) else max_latency
        
        # First token latency
        first_token_latencies = [m.first_token_latency_ms for m in metrics if m.first_token_latency_ms > 0]
        avg_first_token = sum(first_token_latencies) / len(first_token_latencies) if first_token_latencies else 0
        
        # Intent confidence
        intent_confidences = [m.intent_confidence for m in metrics if m.intent_confidence > 0]
        avg_intent_confidence = sum(intent_confidences) / len(intent_confidences) if intent_confidences else 0
        
        # Intent distribution
        intent_counts = defaultdict(int)
        for m in metrics:
            if m.intent_name:
                intent_counts[m.intent_name] += 1
        
        # Unique sessions
        unique_sessions = len(set(m.session_id for m in metrics))
        
        return {
            "time_window_minutes": time_window_minutes or "all",
            "timestamp": datetime.utcnow().isoformat(),
            
            # Counts
            "total_conversations": total_count,
            "unique_sessions": unique_sessions,
            "error_count": error_count,
            "error_rate": error_count / total_count if total_count > 0 else 0,
            "interruption_count": interrupt_count,
            "interruption_rate": interrupt_count / total_count if total_count > 0 else 0,
            
            # Latency
            "latency": {
                "average_ms": round(avg_latency, 2),
                "min_ms": round(min_latency, 2),
                "max_ms": round(max_latency, 2),
                "p95_ms": round(p95_latency, 2),
                "p99_ms": round(p99_latency, 2),
                "avg_first_token_ms": round(avg_first_token, 2)
            },
            
            # Quality
            "quality": {
                "avg_intent_confidence": round(avg_intent_confidence, 2),
                "high_confidence_rate": sum(
                    1 for c in intent_confidences if c >= 0.8
                ) / len(intent_confidences) if intent_confidences else 0
            },
            
            # Intent distribution
            "intent_distribution": dict(intent_counts),
            
            # Average message lengths
            "avg_user_message_length": sum(m.user_message_length for m in metrics) / total_count,
            "avg_assistant_message_length": sum(m.assistant_message_length for m in metrics) / total_count,
            "avg_sentences_per_response": sum(m.sentences_sent for m in metrics) / total_count
        }
    
    def _empty_stats(self) -> Dict[str, Any]:
        """Return empty statistics structure"""
        return {
            "time_window_minutes": 0,
            "timestamp": datetime.utcnow().isoformat(),
            "total_conversations": 0,
            "unique_sessions": 0,
            "error_count": 0,
            "error_rate": 0.0,
            "interruption_count": 0,
            "interruption_rate": 0.0,
            "latency": {
                "average_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "avg_first_token_ms": 0.0
            },
            "quality": {
                "avg_intent_confidence": 0.0,
                "high_confidence_rate": 0.0
            },
            "intent_distribution": {},
            "avg_user_message_length": 0.0,
            "avg_assistant_message_length": 0.0,
            "avg_sentences_per_response": 0.0
        }
    
    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """
        Get summary statistics for a specific session
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session statistics
        """
        metrics = self.session_metrics.get(session_id, [])
        
        if not metrics:
            return {
                "session_id": session_id,
                "total_turns": 0,
                "error": "No metrics found"
            }
        
        return {
            "session_id": session_id,
            "total_turns": len(metrics),
            "avg_latency_ms": sum(m.total_response_time_ms for m in metrics) / len(metrics),
            "total_errors": sum(1 for m in metrics if m.error_occurred),
            "total_interruptions": sum(1 for m in metrics if m.was_interrupted),
            "avg_intent_confidence": sum(
                m.intent_confidence for m in metrics if m.intent_confidence > 0
            ) / len([m for m in metrics if m.intent_confidence > 0]) if any(m.intent_confidence > 0 for m in metrics) else 0,
            "intents_used": list(set(m.intent_name for m in metrics if m.intent_name)),
            "tools_used": list(set(tool for m in metrics for tool in m.tools_used)),
            "duration_minutes": (
                metrics[-1].timestamp - metrics[0].timestamp
            ).total_seconds() / 60 if len(metrics) > 1 else 0
        }
    
    def get_realtime_stats(self) -> Dict[str, Any]:
        """
        Get real-time statistics (last 5 minutes)
        
        Returns:
            Real-time statistics
        """
        return self.get_aggregated_stats(time_window_minutes=5)
    
    def export_metrics(
        self, 
        session_id: Optional[str] = None,
        format: str = "dict"
    ) -> Any:
        """
        Export metrics for external systems
        
        Args:
            session_id: Optional session to export (None = all)
            format: Export format ("dict", "json", "prometheus")
            
        Returns:
            Exported metrics in requested format
        """
        if session_id:
            metrics = self.session_metrics.get(session_id, [])
        else:
            metrics = self.metrics_buffer
        
        if format == "dict":
            return [m.to_dict() for m in metrics]
        elif format == "json":
            import json
            return json.dumps([m.to_dict() for m in metrics], indent=2)
        elif format == "prometheus":
            # Prometheus format (basic)
            lines = []
            stats = self.get_aggregated_stats()
            
            lines.append(f"# HELP june_conversations_total Total conversations")
            lines.append(f"# TYPE june_conversations_total counter")
            lines.append(f"june_conversations_total {stats['total_conversations']}")
            
            lines.append(f"# HELP june_latency_ms Response latency in milliseconds")
            lines.append(f"# TYPE june_latency_ms gauge")
            lines.append(f"june_latency_ms {stats['latency']['average_ms']}")
            
            lines.append(f"# HELP june_error_rate Error rate")
            lines.append(f"# TYPE june_error_rate gauge")
            lines.append(f"june_error_rate {stats['error_rate']}")
            
            return "\n".join(lines)
        
        return None
    
    def clear_session_metrics(self, session_id: str):
        """Clear metrics for a specific session"""
        if session_id in self.session_metrics:
            del self.session_metrics[session_id]
            logger.info(f"Cleared metrics for session {session_id[:8]}...")
    
    def reset(self):
        """Reset all metrics (for testing)"""
        self.metrics_buffer.clear()
        self.session_metrics.clear()
        self.total_conversations = 0
        self.total_errors = 0
        self.total_interruptions = 0
        self.latency_samples.clear()
        logger.info("🔄 Metrics collector reset")


# Global metrics collector instance
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get or create global metrics collector"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def reset_metrics_collector():
    """Reset global metrics collector (for testing)"""
    global _metrics_collector
    _metrics_collector = None