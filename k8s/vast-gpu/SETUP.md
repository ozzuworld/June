# Vast.ai API Key Setup & North America Low Latency Guide

## 🔑 Getting Your Vast.ai API Key

### Step 1: Create Vast.ai Account
1. Go to [console.vast.ai](https://console.vast.ai/)
2. Sign up/Login with your account
3. Add payment method and verify account

### Step 2: Get Your API Key
1. Click on your profile (top-right corner)
2. Go to **"Account"** → **"API Keys"**
3. Click **"Create New API Key"**
4. Copy the generated key (starts with `vast_api_key_...`)

### Step 3: Add to Configuration
Edit your `config.env` file:
```bash
# Replace with your actual API key from console.vast.ai
VAST_API_KEY=vast_api_key_abcd1234567890
```

## 🌎 North America Low Latency Optimization

### Geographic Selection Strategy

The system is **optimized for North America** with this priority order:

#### **Tier 1: US West Coast** (Lowest Latency)
- **US-CA** (California) - Silicon Valley, Los Angeles
- **US-WA** (Washington) - Seattle
- **US-OR** (Oregon) - Portland

#### **Tier 2: US Central/Southwest**
- **US-TX** (Texas) - Dallas, Austin
- **US-CO** (Colorado) - Denver
- **US-AZ** (Arizona) - Phoenix

#### **Tier 3: US East Coast**
- **US-NY** (New York) - NYC, Albany
- **US-FL** (Florida) - Miami
- **US-VA** (Virginia) - Ashburn (AWS region)

#### **Tier 4: Canada Fallback**
- **CA-ON** (Ontario) - Toronto
- **CA-BC** (British Columbia) - Vancouver

## ⚡ How Current API-Aligned Selection Works

### Real Vast.ai API Query (2024/2025)

The Virtual Kubelet constructs queries using **current Vast.ai API parameters**:

```bash
# Equivalent to this vast-cli command:
vast search offers 'rentable=true verified=true geolocation=US gpu_name=RTX_3060 gpu_ram>=12 dph<=0.50 reliability>=0.95 inet_down>=100 inet_up>=100' --order 'dph+,reliability-,inet_down-'
```

### API Parameter Mapping

| Config Setting | Vast.ai API Parameter | Example Value |
|---|---|---|
| `VAST_GPU_TYPE=RTX3060` | `gpu_name=RTX_3060` | Exact GPU model |
| `VAST_MIN_GPU_MEMORY=12` | `gpu_ram>=12` | Minimum VRAM (GB) |
| `VAST_MAX_PRICE_PER_HOUR=0.50` | `dph<=0.50` | Max dollars per hour |
| `VAST_RELIABILITY_SCORE=0.95` | `reliability>=0.95` | Min reliability % |
| `VAST_MIN_DOWNLOAD_SPEED=100` | `inet_down>=100` | Min download (Mbps) |
| `VAST_MIN_UPLOAD_SPEED=100` | `inet_up>=100` | Min upload (Mbps) |
| `VAST_DATACENTER_LOCATION=US` | `geolocation=US` | Geographic filter |
| `VAST_VERIFIED_ONLY=true` | `verified=true` | Verified hosts only |
| `VAST_RENTABLE_ONLY=true` | `rentable=true` | Available for rent |

### Advanced Scoring Algorithm

**Latency-First Scoring** (Total: 1.0):
- **Latency: 35%** - Network ping time (increased for NA optimization)
- **Price: 25%** - Cost per hour
- **GPU Match: 20%** - Exact GPU type bonus
- **Reliability: 15%** - Host uptime history
- **Availability: 5%** - Current availability

**Geographic Bonuses**:
- **US West Coast**: +20% score bonus
- **US Central**: +15% score bonus  
- **US East Coast**: +10% score bonus
- **Canada**: +5% score bonus
- **Non-North America**: -25% penalty

## 📊 Real-Time Selection Example

### Typical Selection Flow
```
[VAST-NA] Querying API: geolocation=US gpu_name=RTX_3060 dph<=0.50...
[VAST-NA] Found 34 instances, scoring for North America optimization:

Instance 12345 (US-CA, San Jose):
  - Base Score: 0.82 (price: $0.23/hr, reliability: 98.5%)
  - Location Bonus: +0.20 (US West Coast)
  - Latency: 12ms
  - Final Score: 1.02 ⭐ WINNER

Instance 12346 (US-TX, Dallas):
  - Base Score: 0.85 (price: $0.21/hr, reliability: 97.2%)
  - Location Bonus: +0.15 (US Central)
  - Latency: 28ms
  - Final Score: 1.00

Instance 12347 (US-NY, NYC):
  - Base Score: 0.88 (price: $0.19/hr, reliability: 99.1%)
  - Location Bonus: +0.10 (US East Coast)
  - Latency: 45ms
  - Final Score: 0.98

[VAST-NA] Selected: Instance 12345 (optimal latency + location)
[VAST-NA] Launching in US-CA with RTX 3060...
[VAST-NA] Services ready with 12ms average latency:
  - june-stt.default.svc.cluster.local:8001 → 198.51.100.45:42352
  - june-tts.default.svc.cluster.local:8000 → 198.51.100.45:42351
```

## ⚙️ Configuration Templates

### **Budget North America** (~$0.20-0.30/hour)
```bash
# Optimized for cost while staying in North America
VAST_API_KEY=your_vast_api_key_here
VAST_GPU_TYPE=RTX3060
VAST_MAX_PRICE_PER_HOUR=0.35
VAST_RELIABILITY_SCORE=0.90
VAST_DATACENTER_LOCATION=US
VAST_PREFERRED_REGIONS=US-TX,US-CO,US-AZ,US  # Central US for balance
```

### **Performance North America** (~$0.40-0.60/hour)
```bash
# Optimized for performance within North America
VAST_API_KEY=your_vast_api_key_here
VAST_GPU_TYPE=RTX4090
VAST_MAX_PRICE_PER_HOUR=0.70
VAST_MIN_DOWNLOAD_SPEED=200
VAST_RELIABILITY_SCORE=0.98
VAST_DATACENTER_LOCATION=US
VAST_PREFERRED_REGIONS=US-CA,US-WA,US-NY,US  # Premium locations
```

### **Ultra-Low Latency** (West Coast Priority)
```bash
# Maximum performance, West Coast only
VAST_API_KEY=your_vast_api_key_here
VAST_GPU_TYPE=RTX3060
VAST_MAX_PRICE_PER_HOUR=0.50
VAST_MIN_DOWNLOAD_SPEED=150
VAST_RELIABILITY_SCORE=0.95
VAST_DATACENTER_LOCATION=US
VAST_PREFERRED_REGIONS=US-CA,US-WA,US-OR     # West Coast only
```

## 🔍 Monitoring & Troubleshooting

### Check Selection Logs
```bash
# View instance selection process
kubectl logs -n kube-system deployment/virtual-kubelet-vast | grep "VAST-NA"

# Monitor latency and performance
kubectl logs deployment/june-gpu-services | grep "latency\|ms"
```

### Common Issues & Solutions

#### **No Instances Found in North America**
```bash
# Temporarily relax requirements
VAST_MAX_PRICE_PER_HOUR=0.75  # Increase budget
VAST_RELIABILITY_SCORE=0.85   # Lower reliability requirement
# Or allow global fallback:
VAST_PREFERRED_REGIONS=US-CA,US-TX,US-NY,US,CA,EU
```

#### **High Latency Despite North America Selection**
```bash
# Enable strict latency checking
# In vast-provider-config.yaml:
latency_check:
  enabled: true
  max_acceptable_ms: 30  # Stricter limit
  timeout_seconds: 3
```

#### **Instances Keep Failing in Specific Regions**
```bash
# Blacklist problematic hosts
# Add to vast-provider-config.yaml:
blacklist:
  blocked_hosts: ["12345", "12346"]  # Specific host IDs
  # Or avoid entire subregions temporarily
```

## 📈 Expected Performance

### Latency Expectations
- **US West Coast**: 5-20ms (optimal)
- **US Central**: 15-35ms (good)
- **US East Coast**: 25-50ms (acceptable)
- **Canada**: 10-40ms (varies by location)
- **Global Fallback**: 50-150ms (backup only)

### Typical Selection Times
- **API Query**: 1-3 seconds
- **Instance Launch**: 30-90 seconds
- **Service Health Check**: 60-180 seconds
- **Total Deployment**: 2-4 minutes

### Cost Optimization
- **RTX 3060 (12GB)**: $0.15-0.45/hour in North America
- **Multi-Service Sharing**: ~60% cost savings vs separate instances
- **Auto-scaling**: Scale to zero when unused

## 🚀 Quick Start

1. **Get API Key**: Visit [console.vast.ai](https://console.vast.ai/)
2. **Configure**: Add `VAST_API_KEY` to your `config.env`
3. **Deploy**: The system automatically optimizes for North America
4. **Monitor**: Check logs for latency and selection decisions

The Virtual Kubelet will automatically prioritize North American instances with the lowest latency while staying within your budget and performance requirements!