# June STT Service

Advanced Speech-to-Text microservice powered by OpenAI Whisper with Keycloak authentication and orchestrator integration.

## Features

- **State-of-the-art ASR**: Uses OpenAI Whisper (Large v3) for high-accuracy transcription
- **Multi-format Support**: Handles various audio formats (WAV, MP3, M4A, etc.)
- **Async Processing**: Non-blocking transcription with proper FastAPI async patterns
- **Authentication**: Keycloak integration with fallback mode for development
- **Orchestrator Integration**: Seamless communication with June orchestrator service
- **Resource Management**: Automatic cleanup of old transcripts and temp files
- **Health Monitoring**: Comprehensive health checks and monitoring endpoints
- **Error Resilience**: Robust error handling and recovery

## Quick Start

### Local Development

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   pip install -e ./shared/
   ```

2. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

3. **Run Service**:
   ```bash
   python app.py
   # or
   uvicorn app:app --host 0.0.0.0 --port 8080 --reload
   ```

### Docker Deployment

```bash
# Build image
docker build -t ozzuworld/june-stt .

# Run container
docker run -p 8080:8080 \
  -e WHISPER_MODEL=large-v3 \
  -e ORCHESTRATOR_URL=http://orchestrator:8080 \
  ozzuworld/june-stt
```

## API Endpoints

### Core Transcription

#### `POST /v1/transcribe`
Transcribe an audio file to text.

**Request**:
- `audio_file`: Audio file (multipart/form-data)
- `language`: Source language code (optional, auto-detected)
- `task`: "transcribe" or "translate" (default: "transcribe")
- `temperature`: Sampling temperature 0.0-1.0 (default: 0.0)
- `notify_orchestrator`: Send result to orchestrator (default: true)

**Response**:
```json
{
  "transcript_id": "uuid",
  "text": "Transcribed text content",
  "language": "en",
  "processing_time_ms": 1250,
  "timestamp": "2025-09-28T19:30:00Z",
  "status": "completed",
  "user_id": "user_uuid"
}
```

#### `GET /v1/transcripts/{transcript_id}`
Retrieve a specific transcript by ID.

#### `GET /v1/transcripts`
List recent transcripts for the authenticated user.

#### `DELETE /v1/transcripts/{transcript_id}`
Delete a specific transcript.

### Monitoring

#### `GET /healthz`
Detailed health check for monitoring systems.

#### `GET /v1/stats`
Service statistics and metrics.

#### `GET /`
General service information and endpoint listing.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | Service port |
| `WHISPER_MODEL` | `large-v3` | Whisper model to use |
| `ORCHESTRATOR_URL` | `http://localhost:8080` | Orchestrator service URL |
| `ORCHESTRATOR_API_KEY` | `` | API key for orchestrator |
| `KEYCLOAK_URL` | `` | Keycloak server URL (optional) |
| `KEYCLOAK_REALM` | `allsafe` | Keycloak realm name |
| `TRANSCRIPT_RETENTION_HOURS` | `24` | How long to keep transcripts |

### Whisper Models

Supported Whisper models (trade-off between speed and accuracy):
- `tiny`: Fastest, least accurate (~39 MB)
- `base`: Good balance (~74 MB)
- `small`: Better accuracy (~244 MB)
- `medium`: High accuracy (~769 MB)
- `large`: Highest accuracy (~1550 MB)
- `large-v2`: Improved large model
- `large-v3`: Latest and most accurate (~1550 MB)

## Architecture

### Service Components

1. **WhisperService**: Manages model loading and transcription
2. **OrchestratorClient**: Handles communication with orchestrator
3. **Authentication**: Keycloak integration with fallback
4. **Background Tasks**: Cleanup and maintenance
5. **Storage**: In-memory transcript management

### Processing Flow

```
Audio Upload → Validation → Temp Storage → Whisper Processing → 
Result Storage → Orchestrator Notification → Response
```

### Error Handling

- **File Validation**: Type and size checks
- **Model Loading**: Graceful degradation and retry
- **Processing Errors**: Detailed error responses
- **Resource Cleanup**: Automatic temp file removal
- **Background Tasks**: Error recovery and logging

## Performance Considerations

### Model Loading
- Models are loaded asynchronously to avoid blocking
- Lazy loading on first transcription request
- Thread pool execution for CPU-intensive tasks

### Memory Management
- Automatic transcript cleanup after 24 hours (configurable)
- Temporary file cleanup after processing
- Periodic background maintenance tasks

### Scalability
- Stateless design for horizontal scaling
- Async request processing
- Resource pooling for concurrent requests

## Security

### Authentication
- Keycloak JWT token validation
- User-scoped transcript access
- Service-to-service authentication for orchestrator

### File Handling
- Secure temporary file storage
- Size limits (100MB default)
- Format validation
- Automatic cleanup

## Monitoring & Observability

### Health Checks
- Model loading status
- Memory usage tracking
- Service connectivity

### Logging
- Structured logging with timestamps
- Processing metrics
- Error tracking
- Performance monitoring

### Metrics Available
- Transcription processing time
- Active transcript count
- Model status
- Authentication status

## Development

### Testing

```bash
# Run tests
pytest tests/

# Test with audio file
curl -X POST "http://localhost:8080/v1/transcribe" \
  -H "Authorization: Bearer your-token" \
  -F "audio_file=@test-audio.wav"
```

### Debugging

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
python app.py

# Check model status
curl http://localhost:8080/healthz
```

### Code Structure

```
june-stt/
├── app.py              # Main FastAPI application
├── requirements.txt    # Python dependencies
├── Dockerfile         # Container configuration
├── .env               # Environment configuration
├── shared/            # Authentication module
│   ├── __init__.py   # Auth functions
│   └── setup.py      # Package configuration
└── README.md         # This file
```

## Deployment

### Docker Hub
Images are automatically built and pushed to `ozzuworld/june-stt` via GitHub Actions.

### Kubernetes
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: june-stt
spec:
  replicas: 2
  selector:
    matchLabels:
      app: june-stt
  template:
    metadata:
      labels:
        app: june-stt
    spec:
      containers:
      - name: june-stt
        image: ozzuworld/june-stt:latest
        ports:
        - containerPort: 8080
        env:
        - name: WHISPER_MODEL
          value: "large-v3"
        - name: ORCHESTRATOR_URL
          value: "http://june-orchestrator:8080"
        resources:
          requests:
            memory: "2Gi"
            cpu: "1"
          limits:
            memory: "4Gi"
            cpu: "2"
```

## Troubleshooting

### Common Issues

1. **Model Loading Errors**:
   - Check available disk space
   - Verify internet connectivity for model download
   - Try smaller model (`base` instead of `large-v3`)

2. **Memory Issues**:
   - Increase container memory limits
   - Use smaller Whisper model
   - Check transcript cleanup settings

3. **Audio Processing Errors**:
   - Verify ffmpeg installation
   - Check audio file format support
   - Validate file size limits

4. **Authentication Issues**:
   - Verify Keycloak configuration
   - Check token validity
   - Enable fallback mode for testing

### Logs

Check service logs for detailed error information:
```bash
# Docker
docker logs june-stt

# Kubernetes
kubectl logs deployment/june-stt
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Update documentation
6. Submit a pull request

## License

This project is part of the June voice AI platform.
