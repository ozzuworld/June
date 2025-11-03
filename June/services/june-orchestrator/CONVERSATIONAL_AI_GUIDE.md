# Conversational AI Integration Guide

## Overview

This guide explains how to integrate the new ChatGPT-style conversational AI features into your June Orchestrator. The implementation provides context-aware conversations, topic tracking, and memory management for a more natural learning experience.

## Architecture

### Core Components

1. **ConversationMemoryService** - Redis-backed memory management
2. **ConversationalAIProcessor** - Context-aware response generation  
3. **Conversation Routes** - REST API endpoints for chat interactions
4. **Enhanced Dependencies** - Dependency injection for conversation services

## Integration Steps

### Step 1: Update Main Application

Add the conversation router to your main FastAPI app:

```python
from .routes.conversation import router as conversation_router

app.include_router(
    conversation_router, 
    prefix="/api/conversation",
    tags=["Conversational AI"]
)
```

### Step 2: Environment Configuration

Add Redis configuration:

```bash
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=1
```

## API Endpoints

### Chat Conversation
```http
POST /api/conversation/chat
{
  "session_id": "user-session-123",
  "message": "Explain how MCP works"
}
```

### Get History
```http
GET /api/conversation/history/{session_id}
```

## Features

- Context-aware responses
- Intent recognition 
- Learning adaptation
- Topic tracking
- Follow-up suggestions

## Testing

```bash
curl -X POST "http://localhost:8000/api/conversation/chat" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "test", "message": "Explain microservices"}'
```

This transforms your June Orchestrator into an engaging, context-aware learning companion.
