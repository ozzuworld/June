# june-quant (PoC)

Proof-of-concept micro-trading framework with two services:

- **june-quant-signal-service**: FastAPI service that takes a feature vector and
  returns LONG / SHORT / FLAT decisions based on a 0.35% target per trade.
- **june-quant-execution-sim**: FastAPI in-memory execution simulator that
  accepts orders and tracks cash + positions.

## Quick start

```bash
docker-compose up --build
```

Signal service: http://localhost:8000  
Execution sim: http://localhost:8001
```
