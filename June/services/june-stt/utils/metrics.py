"""Performance metrics utilities for June STT"""
import time
from typing import Dict, List
from dataclasses import dataclass, field
from collections import deque

@dataclass
class PerformanceMetrics:
    """Track STT performance metrics"""
    partial_processing_times: deque = field(default_factory=lambda: deque(maxlen=100))
    final_processing_times: deque = field(default_factory=lambda: deque(maxlen=100))
    ultra_fast_partials: int = 0
    total_partials: int = 0
    total_finals: int = 0
    start_time: float = field(default_factory=time.time)
    
    def record_partial(self, processing_time_ms: float, ultra_fast: bool = False):
        """Record partial transcript processing time"""
        self.partial_processing_times.append(processing_time_ms)
        self.total_partials += 1
        if ultra_fast:
            self.ultra_fast_partials += 1
    
    def record_final(self, processing_time_ms: float = None):
        """Record final transcript processing"""
        if processing_time_ms:
            self.final_processing_times.append(processing_time_ms)
        self.total_finals += 1
    
    def get_stats(self) -> Dict:
        """Get performance statistics"""
        uptime = time.time() - self.start_time
        
        partial_times = list(self.partial_processing_times)
        final_times = list(self.final_processing_times)
        
        return {
            "uptime_seconds": round(uptime, 1),
            "total_partials": self.total_partials,
            "total_finals": self.total_finals,
            "ultra_fast_partials": self.ultra_fast_partials,
            "ultra_fast_rate": f"{(self.ultra_fast_partials / max(1, self.total_partials) * 100):.1f}%",
            "avg_partial_processing_ms": round(sum(partial_times) / len(partial_times), 1) if partial_times else 0,
            "avg_final_processing_ms": round(sum(final_times) / len(final_times), 1) if final_times else 0,
            "min_partial_processing_ms": min(partial_times) if partial_times else 0,
            "max_partial_processing_ms": max(partial_times) if partial_times else 0,
            "partials_per_minute": round((self.total_partials / max(1, uptime)) * 60, 1),
        }
    
    def reset(self):
        """Reset all metrics"""
        self.partial_processing_times.clear()
        self.final_processing_times.clear()
        self.ultra_fast_partials = 0
        self.total_partials = 0
        self.total_finals = 0
        self.start_time = time.time()

# Global metrics instance
streaming_metrics = PerformanceMetrics()
