#!/usr/bin/env python3
# COMPLETE TTS SERVICE WITH FULL DEBUG LOGGING BUILT-IN
# NO MANUAL IMPORTS NEEDED - EVERYTHING IS HERE

import logging
import time
import traceback
import asyncio
import json
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
import uvicorn

# Enable full debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/tts_debug.log')
    ]
)

# Create specific logger for TTS debugging
debug_logger = logging.getLogger("TTS-DEBUG")

class FullDebugMiddleware(BaseHTTPMiddleware):
    """Logs EVERY SINGLE REQUEST in extreme detail"""
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Log incoming request with maximum detail
        debug_logger.info("=" * 80)
        debug_logger.info(f"🔥🔥🔥 INCOMING REQUEST DETECTED 🔥🔥🔥")
        debug_logger.info(f"   ⏰ Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S.%f')}")
        debug_logger.info(f"   📍 Method: {request.method}")
        debug_logger.info(f"   🌐 Full URL: {str(request.url)}")
        debug_logger.info(f"   📁 Path: {request.url.path}")
        debug_logger.info(f"   🔗 Query String: {request.url.query}")
        debug_logger.info(f"   💻 Client IP: {request.client.host}")
        debug_logger.info(f"   🔌 Client Port: {request.client.port}")
        debug_logger.info(f"   🌍 Remote Address: {request.client}")
        
        # Log ALL headers in detail
        debug_logger.info(f"   📋 REQUEST HEADERS ({len(request.headers)} total):")
        for key, value in request.headers.items():
            debug_logger.info(f"     📝 {key}: {value}")
        
        # Log query parameters
        if request.query_params:
            debug_logger.info(f"   ❓ Query Parameters:")
            for key, value in request.query_params.items():
                debug_logger.info(f"     🔍 {key}: {value}")
        
        # For POST/PUT/PATCH requests, capture and log the body
        body_data = None
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                body_data = await request.body()
                if body_data:
                    debug_logger.info(f"   📦 Body Size: {len(body_data)} bytes")
                    
                    # Try to decode as text/JSON
                    try:
                        body_text = body_data.decode('utf-8')
                        debug_logger.info(f"   📄 Body Content (text): {body_text}")
                        
                        # Try to parse as JSON for pretty printing
                        try:
                            body_json = json.loads(body_text)
                            debug_logger.info(f"   📋 Body Content (JSON formatted):")
                            debug_logger.info(json.dumps(body_json, indent=2))
                        except json.JSONDecodeError:
                            debug_logger.info(f"   📄 Body is not valid JSON")
                            
                    except UnicodeDecodeError:
                        debug_logger.info(f"   🔢 Body Content (hex): {body_data.hex()[:400]}...")
                        debug_logger.info(f"   ⚠️ Body contains binary data")
                else:
                    debug_logger.info(f"   📭 Body: EMPTY")
                    
            except Exception as body_error:
                debug_logger.error(f"   ❌ Error reading request body: {body_error}")
                debug_logger.error(f"   🔍 Body error traceback: {traceback.format_exc()}")
        
        debug_logger.info(f"   🏁 Starting request processing...")
        
        try:
            # Process the request
            response = await call_next(request)
            
            # Log successful response
            process_time = time.time() - start_time
            debug_logger.info(f"   ✅ REQUEST COMPLETED SUCCESSFULLY")
            debug_logger.info(f"   📊 Status Code: {response.status_code}")
            debug_logger.info(f"   ⏱️ Processing Time: {process_time:.4f} seconds")
            
            # Log response headers
            debug_logger.info(f"   📋 RESPONSE HEADERS:")
            for key, value in response.headers.items():
                debug_logger.info(f"     📝 {key}: {value}")
                
            debug_logger.info("=" * 80)
            return response
            
        except Exception as process_error:
            # Log any processing errors
            process_time = time.time() - start_time
            debug_logger.error(f"   ❌❌❌ REQUEST PROCESSING FAILED ❌❌❌")
            debug_logger.error(f"   🚨 Error Message: {str(process_error)}")
            debug_logger.error(f"   🔍 Error Type: {type(process_error).__name__}")
            debug_logger.error(f"   ⏱️ Processing Time: {process_time:.4f} seconds")
            debug_logger.error(f"   📚 Full Traceback:")
            debug_logger.error(traceback.format_exc())
            debug_logger.error("=" * 80)
            raise

# Create FastAPI app with debug logging
app = FastAPI(
    title="June TTS Service - DEBUG MODE",
    description="TTS Service with Full Debug Logging",
    version="4.0.0-debug"
)

# Add the debug middleware
app.add_middleware(FullDebugMiddleware)

@app.on_event("startup")
async def startup_event():
    """Log startup information and network status"""
    debug_logger.info("🚀🚀🚀 JUNE TTS SERVICE STARTING WITH MAXIMUM DEBUG MODE 🚀🚀🚀")
    
    # Log network information
    import socket
    import subprocess
    
    debug_logger.info("🌐 NETWORK DEBUG INFORMATION:")
    debug_logger.info("-" * 50)
    
    try:
        hostname = socket.gethostname()
        debug_logger.info(f"📍 Hostname: {hostname}")
        
        local_ip = socket.gethostbyname(hostname)
        debug_logger.info(f"🏠 Local IP: {local_ip}")
        
        # Get all network interfaces
        import psutil
        interfaces = psutil.net_if_addrs()
        debug_logger.info(f"🔌 Network Interfaces:")
        for interface, addresses in interfaces.items():
            debug_logger.info(f"  Interface: {interface}")
            for addr in addresses:
                debug_logger.info(f"    {addr.family.name}: {addr.address}")
                
    except Exception as net_error:
        debug_logger.error(f"❌ Network info error: {net_error}")
    
    # Check port availability
    try:
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_socket.bind(('0.0.0.0', 8000))
        test_socket.close()
        debug_logger.info("✅ Port 8000 is available for binding")
    except Exception as port_error:
        debug_logger.error(f"❌ Port 8000 binding issue: {port_error}")
    
    debug_logger.info("-" * 50)
    debug_logger.info("🔍 ALL INCOMING REQUESTS WILL BE LOGGED IN EXTREME DETAIL")
    debug_logger.info("📝 Debug log also saved to: /tmp/tts_debug.log")
    debug_logger.info("🎯 TTS Service ready for debugging")

@app.get("/")
async def root():
    """Root endpoint with debug logging"""
    debug_logger.info("🏠 ROOT ENDPOINT HIT")
    return {
        "service": "June TTS Service",
        "version": "4.0.0-debug",
        "status": "running",
        "debug_mode": "enabled",
        "endpoints": {
            "health": "/health",
            "healthz": "/healthz", 
            "synthesize": "/synthesize",
            "v1_tts": "/v1/tts",
            "voices": "/v1/voices"
        }
    }

@app.get("/health")
@app.get("/healthz")
async def health_check():
    """Health check endpoint with debug logging"""
    debug_logger.info("💚 HEALTH CHECK ENDPOINT HIT")
    debug_logger.info(f"   ⏰ Health check at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    debug_logger.info(f"   🎯 Service status: HEALTHY")
    
    return {
        "status": "healthy",
        "service": "june-tts",
        "version": "4.0.0-debug",
        "timestamp": time.time(),
        "debug_enabled": True
    }

@app.post("/synthesize")
@app.post("/v1/tts")
async def synthesize_speech(request: Request):
    """TTS synthesis endpoint with maximum debug logging"""
    debug_logger.info("🎤🎤🎤 SYNTHESIZE ENDPOINT CALLED 🎤🎤🎤")
    
    try:
        # Parse the JSON request
        json_data = await request.json()
        debug_logger.info(f"📥 Received TTS request data:")
        debug_logger.info(json.dumps(json_data, indent=2))
        
        # Extract TTS parameters
        text = json_data.get('text', '')
        voice = json_data.get('voice', 'default')
        mode = json_data.get('mode', 'sft')
        speaker = json_data.get('speaker', voice)
        
        debug_logger.info(f"🎯 TTS Parameters Extracted:")
        debug_logger.info(f"   📝 Text: '{text[:100]}{'...' if len(text) > 100 else ''}' (total length: {len(text)} chars)")
        debug_logger.info(f"   🎵 Voice: {voice}")
        debug_logger.info(f"   🎵 Speaker: {speaker}")
        debug_logger.info(f"   ⚙️ Mode: {mode}")
        
        # Simulate TTS processing (replace with your actual TTS logic)
        debug_logger.info("🔊 Starting TTS synthesis...")
        
        # Simulate processing time
        await asyncio.sleep(0.1)
        
        debug_logger.info("✅ TTS synthesis completed successfully")
        
        # Return success response
        response_data = {
            "status": "success",
            "message": "TTS synthesis completed",
            "text_length": len(text),
            "voice": voice,
            "speaker": speaker,
            "mode": mode,
            "processing_time": 0.1
        }
        
        debug_logger.info(f"📤 Sending response:")
        debug_logger.info(json.dumps(response_data, indent=2))
        
        return response_data
        
    except json.JSONDecodeError as json_error:
        debug_logger.error(f"❌ JSON parsing error: {json_error}")
        debug_logger.error(f"📚 JSON error traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=400, detail="Invalid JSON in request body")
        
    except Exception as synthesis_error:
        debug_logger.error(f"❌❌❌ SYNTHESIS ERROR: {str(synthesis_error)}")
        debug_logger.error(f"🔍 Error type: {type(synthesis_error).__name__}")
        debug_logger.error(f"📚 Full traceback:")
        debug_logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(synthesis_error)}")

@app.get("/v1/voices")
async def get_voices():
    """Get available voices"""
    debug_logger.info("🎵 VOICES ENDPOINT HIT")
    return {
        "voices": [
            {"id": "英文女", "name": "English Female", "language": "en"},
            {"id": "英文男", "name": "English Male", "language": "en"},
            {"id": "中文女", "name": "Chinese Female", "language": "zh"},
            {"id": "中文男", "name": "Chinese Male", "language": "zh"}
        ]
    }

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler with debug logging"""
    debug_logger.error(f"🚨🚨🚨 UNHANDLED EXCEPTION OCCURRED 🚨🚨🚨")
    debug_logger.error(f"   🔍 Exception type: {type(exc).__name__}")
    debug_logger.error(f"   📝 Exception message: {str(exc)}")
    debug_logger.error(f"   🌐 Request URL: {request.url}")
    debug_logger.error(f"   📍 Request method: {request.method}")
    debug_logger.error(f"   📚 Full traceback:")
    debug_logger.error(traceback.format_exc())
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),
            "type": type(exc).__name__
        }
    )

if __name__ == "__main__":
    debug_logger.info("🔥🔥🔥 STARTING TTS SERVICE WITH UVICORN - MAXIMUM DEBUG MODE 🔥🔥🔥")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="debug",
        access_log=True,
        reload=False  # Disable reload in production
    )