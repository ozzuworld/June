# June Dark OSINT Framework

**Advanced Open Source Intelligence Platform with Computer Vision and Threat Intelligence**

## Overview

June Dark is a sophisticated OSINT (Open Source Intelligence) framework that combines state-of-the-art computer vision with threat intelligence capabilities. It processes visual media to extract actionable intelligence and automatically enriches findings with threat data from OpenCTI.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        June Dark OSINT                         │
├─────────────────────────────────────────────────────────────────┤
│  FastAPI Web Interface                                          │
├─────────────────┬───────────────────┬───────────────────────────┤
│   YOLOv11       │   OpenCTI Client  │   Vision Services         │
│   Detector      │   Integration     │   Pipeline                │
├─────────────────┼───────────────────┼───────────────────────────┤
│ GPU Processing  │ Threat Intel DB   │ Queue Management          │
│ • Object Det.   │ • Indicators      │ • Redis Cache             │
│ • Face Recog.   │ • Observables     │ • RabbitMQ                │
│ • OCR           │ • Reports         │ • Background Tasks        │
├─────────────────┼───────────────────┼───────────────────────────┤
│                 Data Storage Layer                              │
│ Elasticsearch  │  Neo4j Graph     │  PostgreSQL               │
│ MinIO Objects  │  Artifacts       │  Logs                     │
└─────────────────────────────────────────────────────────────────┘
```

## Core Capabilities

### 🔍 Computer Vision Analysis
- **YOLOv11 Object Detection**: Latest YOLO model for real-time object identification
- **Face Recognition**: InsightFace integration for person identification
- **OCR Processing**: Tesseract for text extraction from images
- **CLIP Embeddings**: Visual similarity search and classification
- **Batch Processing**: Efficient multi-image analysis

### 🛡️ Threat Intelligence Integration
- **OpenCTI Integration**: Full STIX 2.1 compatibility
- **Indicator Enrichment**: Automatic threat context for detections
- **Relationship Mapping**: Visual evidence linked to threat actors
- **Intelligence Reporting**: Automated OSINT report generation
- **IOC Management**: Create and manage indicators of compromise

### ⚡ Performance Features
- **GPU Acceleration**: CUDA-optimized inference
- **Async Processing**: Non-blocking operations
- **Resource Management**: Smart GPU memory allocation
- **Caching Layer**: Redis-based result caching
- **Queue System**: RabbitMQ for task distribution

## What to Expect When Running

### System Startup Sequence

1. **Container Initialization** (30-60 seconds)
   ```
   [INFO] Initializing June Dark OSINT Framework...
   [INFO] Loading YOLOv11 model: yolo11s.pt
   [INFO] Model loaded on GPU: NVIDIA GeForce RTX 4090
   [INFO] Connecting to OpenCTI: http://opencti:8080
   [INFO] Connected to OpenCTI: version 6.3.7
   [INFO] June Dark OSINT Framework initialized successfully
   ```

2. **Health Check Response**
   ```json
   {
     "status": "healthy",
     "timestamp": "2025-09-29T03:55:00Z",
     "services": {
       "yolo": true,
       "opencti": true,
       "gpu": true,
       "gpu_name": "NVIDIA GeForce RTX 4090",
       "queue_manager": true
     },
     "model": "YOLOv11",
     "version": "2.0.0"
   }
   ```

3. **Available Endpoints**
   - `http://localhost:9009/health` - System status
   - `http://localhost:9009/docs` - Interactive API documentation
   - `http://localhost:9009/detect/objects` - Single image analysis
   - `http://localhost:9009/detect/batch` - Batch processing
   - `http://localhost:9009/opencti/indicators` - Threat intelligence

### Expected Performance Metrics

#### Single Image Processing
- **YOLOv11n (Nano)**: ~15ms on RTX 4090, ~200ms on CPU
- **YOLOv11s (Small)**: ~25ms on RTX 4090, ~400ms on CPU
- **YOLOv11m (Medium)**: ~45ms on RTX 4090, ~800ms on CPU

#### Batch Processing (10 images)
- **GPU Batch**: ~150ms total (15ms per image)
- **CPU Batch**: ~2.5s total (250ms per image)

#### Memory Usage
- **Base Container**: ~2GB RAM
- **YOLOv11s Model**: ~20MB VRAM
- **Per Image**: ~50MB VRAM during processing

### Example API Usage

#### Object Detection
```bash
curl -X POST "http://localhost:9009/detect/objects" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@suspicious_image.jpg"
```

**Expected Response:**
```json
{
  "image_id": "uuid-12345",
  "detections": [
    {
      "id": "det-001",
      "class_id": 0,
      "class_name": "person",
      "confidence": 0.92,
      "bbox": [120, 80, 350, 420],
      "center": [235, 250],
      "timestamp": "2025-09-29T03:55:15Z"
    }
  ],
  "opencti_indicators": [
    {
      "id": "indicator-001",
      "pattern": "[file:hashes.MD5 = 'd41d8cd98f00b204e9800998ecf8427e']",
      "labels": ["suspicious-person", "surveillance"]
    }
  ],
  "threat_level": "medium",
  "metadata": {
    "filename": "suspicious_image.jpg",
    "detection_count": 1,
    "model": "YOLOv11s"
  }
}
```

## Component Details

### YOLOv11 Detector (`models/yolo_detector.py`)

**Purpose**: Real-time object detection and classification

**Key Features**:
- Multiple model sizes (nano to extra-large)
- Priority class detection for OSINT scenarios
- Performance monitoring and statistics
- GPU memory optimization
- Warmup routines for consistent performance

**OSINT-Specific Classes**:
```python
PRIORITY_CLASSES = {
    'person', 'car', 'motorcycle', 'bicycle', 'truck', 'bus',
    'laptop', 'cell phone', 'backpack', 'handbag', 'suitcase',
    'knife', 'scissors', 'stop sign', 'traffic light'
}
```

### OpenCTI Client (`models/opencti_client.py`)

**Purpose**: Threat intelligence integration and enrichment

**Capabilities**:
- Create and manage STIX indicators
- Search existing threat intelligence
- Enrich visual detections with context
- Generate intelligence reports
- Bulk operations for efficiency

**Supported Indicator Types**:
```python
INDICATOR_TYPES = {
    'file': 'File',
    'url': 'Url', 
    'domain': 'Domain-Name',
    'ipv4': 'IPv4-Addr',
    'email': 'Email-Addr',
    'hash_sha256': 'File'
}
```

### Vision Service (`services/vision_service.py`)

**Purpose**: Orchestrates computer vision pipeline

**Workflow**:
1. Image preprocessing and validation
2. YOLOv11 object detection
3. Face recognition (if enabled)
4. OCR text extraction
5. CLIP feature extraction
6. Result aggregation and scoring

### OpenCTI Service (`services/opencti_service.py`)

**Purpose**: Threat intelligence automation

**Functions**:
- Automatic indicator creation from detections
- Context enrichment for suspicious objects
- Relationship mapping between entities
- Report generation for analysts
- IOC management and updates

## Configuration

### Environment Variables

```bash
# OpenCTI Configuration
OPENCTI_URL=http://opencti:8080
OPENCTI_TOKEN=your-api-token
OPENCTI_SSL_VERIFY=true

# YOLO Configuration  
YOLO_MODEL_SIZE=small  # nano, small, medium, large, extra_large
YOLO_CONFIDENCE=0.4
YOLO_IOU_THRESHOLD=0.7

# Redis Configuration
REDIS_URL=redis://redis:6379/0
REDIS_CACHE_TTL=3600

# RabbitMQ Configuration
RABBIT_URL=amqp://guest:guest@rabbitmq:5672//

# GPU Configuration
CUDA_VISIBLE_DEVICES=0
GPU_MEMORY_FRACTION=0.8

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

### Docker Compose Integration

The service integrates with your existing docker-compose.yml:

```yaml
services:
  june-dark:
    build:
      context: ./services/june-dark
      dockerfile: Dockerfile.gpu
    environment:
      - OPENCTI_URL=http://opencti:8080
      - OPENCTI_TOKEN=${OPENCTI_TOKEN}
      - REDIS_URL=redis://redis:6379/2
    ports:
      - "9009:9009"
    depends_on:
      - redis
      - rabbitmq
      - opencti
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: ["gpu"]
    networks:
      - osint
```

## Use Cases

### 1. Surveillance Analysis
- **Input**: Security camera footage or images
- **Process**: Detect persons, vehicles, suspicious objects
- **Output**: Threat assessment with OpenCTI enrichment
- **Result**: Automated alerts for security teams

### 2. Social Media Intelligence
- **Input**: Images from social media platforms
- **Process**: Object detection, face recognition, OCR
- **Output**: Structured intelligence reports
- **Result**: Person of interest tracking

### 3. Digital Forensics
- **Input**: Evidence images from investigations
- **Process**: Extract all visual elements and text
- **Output**: Comprehensive forensic report
- **Result**: Admissible evidence documentation

### 4. Threat Actor Profiling
- **Input**: Images associated with threat campaigns
- **Process**: Link visual evidence to known indicators
- **Output**: Threat actor attribution analysis
- **Result**: Enhanced threat intelligence

## Monitoring and Observability

### Health Endpoints

- `GET /health` - Basic health check
- `GET /health/detailed` - Comprehensive system status
- `GET /metrics` - Prometheus metrics
- `GET /gpu/status` - GPU utilization
- `GET /queue/status` - Queue depths and processing rates

### Logging Output

```json
{
  "timestamp": "2025-09-29T03:55:30Z",
  "level": "INFO",
  "service": "june-dark",
  "component": "yolo_detector",
  "message": "Processed batch of 5 images",
  "metrics": {
    "processing_time": 0.125,
    "detections_count": 23,
    "gpu_memory_used": "15%"
  }
}
```

### Performance Metrics

- **Images processed per second**
- **Average detection confidence**
- **GPU utilization percentage**
- **Memory usage trends**
- **OpenCTI API response times**
- **Queue processing rates**

## Troubleshooting

### Common Issues

1. **GPU Not Available**
   ```
   Error: CUDA device not found
   Solution: Ensure nvidia-docker2 is installed and GPU is visible
   ```

2. **OpenCTI Connection Failed**
   ```
   Error: Failed to connect to OpenCTI
   Solution: Verify OPENCTI_URL and OPENCTI_TOKEN environment variables
   ```

3. **Model Loading Timeout**
   ```
   Error: YOLOv11 model failed to load
   Solution: Increase container memory or use smaller model size
   ```

4. **High Memory Usage**
   ```
   Warning: GPU memory usage > 90%
   Solution: Reduce batch size or use model quantization
   ```

### Debug Mode

```bash
docker run --gpus all -p 9009:9009 \
  -e LOG_LEVEL=DEBUG \
  -e CUDA_LAUNCH_BLOCKING=1 \
  june-dark:latest
```

## Security Considerations

- **Input Validation**: All uploads are validated for type and size
- **Rate Limiting**: API endpoints have configurable rate limits
- **Access Control**: JWT-based authentication available
- **Audit Logging**: All operations are logged with user context
- **Data Encryption**: TLS encryption for all external communications
- **Secrets Management**: Environment-based credential storage

## License

This project is part of the June OSINT platform and follows the same licensing terms.

---

**June Dark OSINT Framework** - Advanced intelligence through computer vision and threat correlation.