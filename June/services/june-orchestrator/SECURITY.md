# June Orchestrator Security Features

## 🔒 Security Enhancements Overview

The June Orchestrator has been enhanced with comprehensive security features to prevent duplicate message processing, control API costs, and protect against abuse.

## 🚨 Critical Security Protections

### 1. Duplicate Message Detection
**Location**: `app/security/rate_limiter.py` - `DuplicationDetector`

**Protection**:
- Tracks processed messages by content hash and message ID
- Prevents duplicate STT messages from triggering multiple AI calls
- Automatic cleanup of old entries (10-minute window)
- Session-based tracking

**Benefits**:
- Eliminates duplicate Gemini API calls from STT retries
- Protects against audio chunk overlap processing
- Prevents network retry loops from multiplying costs

### 2. Rate Limiting
**Location**: `app/security/rate_limiter.py` - `RateLimiter`

**Limits**:
- **AI Calls**: 5 per minute, 50 per hour per user
- **General Requests**: 10 per minute per user
- **Block Duration**: 15 minutes for violators

**Benefits**:
- Prevents rapid-fire API abuse
- Protects against malicious users
- Controls per-user API consumption

### 3. Cost Tracking & Monitoring
**Location**: `app/security/cost_tracker.py` - `AICallTracker`

**Limits**:
- **Daily Cost**: $50 maximum
- **Daily Calls**: 2,000 maximum
- **Hourly Calls**: 200 maximum
- **Daily Tokens**: 1M maximum

**Features**:
- Real-time cost calculation
- Alert thresholds at $10, $25, $40
- Automatic daily/hourly resets
- Token usage estimation

### 4. Circuit Breaker
**Location**: `app/security/cost_tracker.py` - `CircuitBreaker`

**Protection**:
- Automatically stops AI calls when limits are exceeded
- Manual open/close controls for emergencies
- 30-minute recovery timeout
- Prevents bill explosion scenarios

## 📈 Security Endpoints

### Monitoring
```
GET /api/security/stats - Get security system statistics
GET /api/sessions/stats - Enhanced stats with security metrics
GET /healthz - Health check with security status
```

### Emergency Controls
```
POST /api/security/circuit-breaker/open - Emergency stop (manual)
POST /api/security/circuit-breaker/close - Restore service (manual)
```

## 🔧 Integration Points

### STT Webhook Protection
**Location**: `app/routes/webhooks.py`

**Security Checks**:
1. **Rate Limiting** - Blocks excessive requests per user
2. **Circuit Breaker** - Stops processing if limits exceeded
3. **Duplicate Detection** - Prevents duplicate message processing
4. **AI Rate Limiting** - Additional limits for AI calls specifically
5. **Cost Tracking** - Monitors every API call

### AI Service Protection
**Location**: `app/services/ai_service.py`

**Security Features**:
1. **Input Validation** - Length limits and sanitization
2. **Circuit Breaker Check** - Pre-call validation
3. **Token Limits** - Hard limits on input tokens
4. **Cost Calculation** - Per-call cost estimation
5. **Enhanced Error Handling** - Security-aware error responses

## ⚠️ Alert Thresholds

### Cost Alerts
- **$10** - First warning
- **$25** - High usage warning  
- **$40** - Critical usage warning
- **$50** - Circuit breaker triggers (service stops)

### Usage Alerts
- **80% of daily calls** - High volume warning
- **80% of daily tokens** - High token usage warning
- **Rate limit violations** - User blocking notifications

## 📄 Logging & Monitoring

### Security Logs
- All duplicate messages blocked
- Rate limiting violations
- Cost threshold breaches
- Circuit breaker activations
- Suspicious input patterns

### Background Monitoring
- **Security monitoring task** runs every 5 minutes
- **Cost warnings** logged automatically
- **Hourly security summaries**
- **Health check degradation** when limits approached

## 🛑 Emergency Procedures

### If Bill is Exploding
1. **Immediate**: `POST /api/security/circuit-breaker/open`
2. **Check**: `GET /api/security/stats` for current usage
3. **Investigate**: Check logs for duplicate patterns
4. **Restore**: `POST /api/security/circuit-breaker/close` when safe

### If Service is Degraded
1. **Check Health**: `GET /healthz` for issues
2. **Review Stats**: `GET /api/security/stats` for metrics
3. **Check Logs**: Look for security warnings
4. **Reset if needed**: Restart service to reset counters

## 🔐 Configuration

### Environment Variables
```bash
# Rate Limiting (optional - defaults provided)
RATE_LIMIT_AI_PER_MINUTE=5
RATE_LIMIT_AI_PER_HOUR=50
RATE_LIMIT_REQUESTS_PER_MINUTE=10

# Cost Limits (optional - defaults provided)
MAX_DAILY_COST=50.0
MAX_DAILY_CALLS=2000
MAX_HOURLY_CALLS=200

# Circuit Breaker (optional - defaults provided)
CIRCUIT_BREAKER_RECOVERY_MINUTES=30
```

### Default Security Settings
All security features are **enabled by default** with conservative limits to protect your bill while maintaining good user experience.

## 📊 Metrics Dashboard

The root endpoint (`/`) now includes comprehensive security metrics:

```json
{
  "security": {
    "rate_limiter": {
      "total_users_tracked": 5,
      "blocked_users": 0,
      "ai_calls_per_minute_limit": 5
    },
    "cost_tracker": {
      "daily_cost": 1.23,
      "remaining_cost": 48.77,
      "daily_calls": 156,
      "utilization": {
        "cost_percent": 2.5
      }
    },
    "circuit_breaker": {
      "is_open": false,
      "failure_count": 0
    }
  }
}
```

## ✅ Testing the Protection

### Test Duplicate Detection
1. Send the same STT webhook payload twice quickly
2. Second call should return `{"status": "duplicate_blocked"}`

### Test Rate Limiting
1. Send 6 AI requests in 1 minute from same user
2. 6th request should return HTTP 429

### Test Circuit Breaker
1. Manually open: `POST /api/security/circuit-breaker/open`
2. All AI calls should return HTTP 503
3. Close: `POST /api/security/circuit-breaker/close`

---

**Your June Orchestrator is now protected against duplicate messages, cost explosions, and API abuse!** 🔒

Redeploy and monitor the logs for security events.