"""AI cost tracking and circuit breaker"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class AICallTracker:
    """Track AI calls, tokens, and costs with daily limits"""
    
    def __init__(self):
        # Daily tracking
        self.daily_calls = 0
        self.daily_tokens = 0
        self.daily_input_tokens = 0
        self.daily_output_tokens = 0
        self.daily_cost = 0.0
        self.last_reset = datetime.utcnow().date()
        
        # Hourly tracking for rate limiting
        self.hourly_calls = 0
        self.last_hour_reset = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        
        # Limits
        self.max_daily_cost = 50.0  # $50 daily limit
        self.max_daily_calls = 2000  # 2000 calls daily limit
        self.max_hourly_calls = 200  # 200 calls hourly limit
        self.max_daily_tokens = 1_000_000  # 1M tokens daily limit
        
        # Alerts
        self.cost_alerts_sent = set()
        
        logger.info("✅ AI call tracker initialized")
        logger.info(f"💰 Daily limits: ${self.max_daily_cost}, {self.max_daily_calls} calls, {self.max_daily_tokens:,} tokens")
    
    def _reset_if_needed(self):
        """Reset counters if day/hour has changed"""
        now = datetime.utcnow()
        today = now.date()
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        
        # Daily reset
        if today != self.last_reset:
            logger.info(f"📅 Daily reset: {self.daily_calls} calls, {self.daily_tokens:,} tokens, ${self.daily_cost:.4f}")
            self.daily_calls = 0
            self.daily_tokens = 0
            self.daily_input_tokens = 0
            self.daily_output_tokens = 0
            self.daily_cost = 0.0
            self.last_reset = today
            self.cost_alerts_sent.clear()
        
        # Hourly reset
        if current_hour != self.last_hour_reset:
            if self.hourly_calls > 0:
                logger.info(f"⏰ Hourly reset: {self.hourly_calls} calls")
            self.hourly_calls = 0
            self.last_hour_reset = current_hour
    
    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation (4 chars ≈ 1 token for English)"""
        return max(1, len(text) // 4)
    
    def calculate_cost(self, input_tokens: int, output_tokens: int, model: str = "gemini-2.0-flash") -> float:
        """Calculate cost for API call
        
        Gemini 2.0 Flash pricing (as of Oct 2024):
        - Input: $0.075 per 1M tokens  
        - Output: $0.30 per 1M tokens
        """
        input_cost = (input_tokens / 1_000_000) * 0.075
        output_cost = (output_tokens / 1_000_000) * 0.30
        return input_cost + output_cost
    
    def can_make_call(self) -> tuple[bool, str]:
        """Check if we can make an AI call within limits"""
        self._reset_if_needed()
        
        # Check daily cost limit
        if self.daily_cost >= self.max_daily_cost:
            return False, f"Daily cost limit reached: ${self.daily_cost:.2f} >= ${self.max_daily_cost}"
        
        # Check daily call limit
        if self.daily_calls >= self.max_daily_calls:
            return False, f"Daily call limit reached: {self.daily_calls} >= {self.max_daily_calls}"
        
        # Check hourly call limit
        if self.hourly_calls >= self.max_hourly_calls:
            return False, f"Hourly call limit reached: {self.hourly_calls} >= {self.max_hourly_calls}"
        
        # Check daily token limit
        if self.daily_tokens >= self.max_daily_tokens:
            return False, f"Daily token limit reached: {self.daily_tokens:,} >= {self.max_daily_tokens:,}"
        
        return True, "OK"
    
    def track_call(self, input_text: str, output_text: str, processing_time_ms: int = 0):
        """Track an AI call with automatic token estimation"""
        self._reset_if_needed()
        
        input_tokens = self.estimate_tokens(input_text)
        output_tokens = self.estimate_tokens(output_text)
        cost = self.calculate_cost(input_tokens, output_tokens)
        
        # Update counters
        self.daily_calls += 1
        self.hourly_calls += 1
        self.daily_tokens += input_tokens + output_tokens
        self.daily_input_tokens += input_tokens
        self.daily_output_tokens += output_tokens
        self.daily_cost += cost
        
        # Log every call
        logger.info(
            f"💰 AI Call tracked: {input_tokens}+{output_tokens}={input_tokens+output_tokens} tokens, "
            f"${cost:.6f}, {processing_time_ms}ms"
        )
        
        # Log daily stats every 10 calls
        if self.daily_calls % 10 == 0:
            logger.info(
                f"📈 Daily stats: {self.daily_calls} calls, {self.daily_tokens:,} tokens, "
                f"${self.daily_cost:.4f} (${self.max_daily_cost - self.daily_cost:.2f} remaining)"
            )
        
        # Send alerts at thresholds
        self._check_alerts()
    
    def _check_alerts(self):
        """Check and send cost/usage alerts"""
        
        # Cost alerts
        cost_thresholds = [10.0, 25.0, 40.0]  # $10, $25, $40
        for threshold in cost_thresholds:
            if self.daily_cost >= threshold and threshold not in self.cost_alerts_sent:
                logger.error(
                    f"🚨 COST ALERT: Daily spend ${self.daily_cost:.2f} reached ${threshold} threshold! "
                    f"(Limit: ${self.max_daily_cost})"
                )
                self.cost_alerts_sent.add(threshold)
        
        # Call volume alerts
        if self.daily_calls >= self.max_daily_calls * 0.8:  # 80% of daily limit
            if "daily_calls_80" not in self.cost_alerts_sent:
                logger.error(
                    f"🚨 USAGE ALERT: {self.daily_calls} API calls today "
                    f"(80% of daily limit: {self.max_daily_calls})"
                )
                self.cost_alerts_sent.add("daily_calls_80")
        
        # Token alerts
        if self.daily_tokens >= self.max_daily_tokens * 0.8:  # 80% of daily limit
            if "daily_tokens_80" not in self.cost_alerts_sent:
                logger.error(
                    f"🚨 TOKEN ALERT: {self.daily_tokens:,} tokens used today "
                    f"(80% of daily limit: {self.max_daily_tokens:,})"
                )
                self.cost_alerts_sent.add("daily_tokens_80")
    
    def get_stats(self) -> Dict:
        """Get current tracking statistics"""
        self._reset_if_needed()
        
        return {
            "daily_calls": self.daily_calls,
            "hourly_calls": self.hourly_calls,
            "daily_tokens": self.daily_tokens,
            "daily_input_tokens": self.daily_input_tokens,
            "daily_output_tokens": self.daily_output_tokens,
            "daily_cost": round(self.daily_cost, 6),
            "remaining_cost": round(self.max_daily_cost - self.daily_cost, 2),
            "remaining_calls": self.max_daily_calls - self.daily_calls,
            "remaining_hourly_calls": self.max_hourly_calls - self.hourly_calls,
            "remaining_tokens": self.max_daily_tokens - self.daily_tokens,
            "limits": {
                "max_daily_cost": self.max_daily_cost,
                "max_daily_calls": self.max_daily_calls,
                "max_hourly_calls": self.max_hourly_calls,
                "max_daily_tokens": self.max_daily_tokens
            },
            "utilization": {
                "cost_percent": round((self.daily_cost / self.max_daily_cost) * 100, 1),
                "calls_percent": round((self.daily_calls / self.max_daily_calls) * 100, 1),
                "tokens_percent": round((self.daily_tokens / self.max_daily_tokens) * 100, 1)
            }
        }


class CircuitBreaker:
    """Emergency circuit breaker to stop AI calls when limits are hit"""
    
    def __init__(self, call_tracker: AICallTracker):
        self.call_tracker = call_tracker
        self.is_open = False
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.recovery_timeout_minutes = 30
        
        logger.info("✅ Circuit breaker initialized")
    
    def should_allow_call(self) -> tuple[bool, str]:
        """Check if AI calls should be allowed"""
        
        # Check if circuit is manually opened
        if self.is_open:
            if self.last_failure_time:
                time_since_failure = datetime.utcnow() - self.last_failure_time
                if time_since_failure > timedelta(minutes=self.recovery_timeout_minutes):
                    logger.info("🔧 Circuit breaker attempting recovery...")
                    self.is_open = False
                    self.failure_count = 0
                    self.last_failure_time = None
                else:
                    remaining = self.recovery_timeout_minutes - time_since_failure.total_seconds() // 60
                    return False, f"Circuit breaker OPEN - recovery in {remaining:.0f} minutes"
            else:
                return False, "Circuit breaker manually OPEN"
        
        # Check call tracker limits
        can_call, reason = self.call_tracker.can_make_call()
        if not can_call:
            self._trigger_circuit_breaker(reason)
            return False, f"Circuit breaker triggered: {reason}"
        
        return True, "OK"
    
    def _trigger_circuit_breaker(self, reason: str):
        """Trigger the circuit breaker"""
        if not self.is_open:
            logger.error(f"🚨 CIRCUIT BREAKER TRIGGERED: {reason}")
            self.is_open = True
            self.failure_count += 1
            self.last_failure_time = datetime.utcnow()
    
    def manual_open(self, reason: str = "Manual override"):
        """Manually open the circuit breaker"""
        logger.error(f"🚨 CIRCUIT BREAKER MANUALLY OPENED: {reason}")
        self.is_open = True
        self.last_failure_time = datetime.utcnow()
    
    def manual_close(self, reason: str = "Manual override"):
        """Manually close the circuit breaker"""
        logger.info(f"🔧 CIRCUIT BREAKER MANUALLY CLOSED: {reason}")
        self.is_open = False
        self.failure_count = 0
        self.last_failure_time = None
    
    def get_status(self) -> Dict:
        """Get circuit breaker status"""
        status = {
            "is_open": self.is_open,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "recovery_timeout_minutes": self.recovery_timeout_minutes
        }
        
        if self.is_open and self.last_failure_time:
            time_since_failure = datetime.utcnow() - self.last_failure_time
            remaining_recovery_time = max(0, self.recovery_timeout_minutes - time_since_failure.total_seconds() // 60)
            status["recovery_time_remaining_minutes"] = remaining_recovery_time
        
        return status


# Global instances
call_tracker = AICallTracker()
circuit_breaker = CircuitBreaker(call_tracker)