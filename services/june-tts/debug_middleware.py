# TTS DEBUG MIDDLEWARE - Add this to your june-tts FastAPI app
# This will log EVERY request coming to the TTS service

import logging
import time
import traceback
from fastapi import Request
from fastapi.middleware.base import BaseHTTPMiddleware

# Enable full debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)

# Create specific logger for TTS debugging
debug_logger = logging.getLogger("TTS-DEBUG")

class TTSDebugMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Log every single incoming request
        debug_logger.info("=" * 60)
        debug_logger.info(f"🔥 NEW REQUEST RECEIVED")
        debug_logger.info(f"   Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        debug_logger.info(f"   Method: {request.method}")
        debug_logger.info(f"   URL: {str(request.url)}")
        debug_logger.info(f"   Path: {request.url.path}")
        debug_logger.info(f"   Client: {request.client.host}:{request.client.port}")
        debug_logger.info(f"   User-Agent: {request.headers.get('user-agent', 'None')}")
        debug_logger.info(f"   Content-Type: {request.headers.get('content-type', 'None')}")
        debug_logger.info(f"   Content-Length: {request.headers.get('content-length', 'None')}")
        
        # Log all headers
        debug_logger.info(f"   All Headers:")
        for key, value in request.headers.items():
            debug_logger.info(f"     {key}: {value}")
        
        # For POST requests, log the body
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.body()
                if body:
                    debug_logger.info(f"   Body Size: {len(body)} bytes")
                    try:
                        # Try to decode as text
                        body_text = body.decode('utf-8')
                        debug_logger.info(f"   Body Content: {body_text}")
                    except:
                        debug_logger.info(f"   Body Content (hex): {body.hex()[:200]}...")
                else:
                    debug_logger.info("   Body: EMPTY")
            except Exception as e:
                debug_logger.error(f"   Body Read Error: {e}")
        
        debug_logger.info("🟡 PROCESSING REQUEST...")
        
        try:
            # Call the actual endpoint
            response = await call_next(request)
            
            # Log response
            process_time = time.time() - start_time
            debug_logger.info(f"✅ REQUEST SUCCESSFUL")
            debug_logger.info(f"   Status Code: {response.status_code}")
            debug_logger.info(f"   Process Time: {process_time:.3f} seconds")
            debug_logger.info(f"   Response Headers:")
            for key, value in response.headers.items():
                debug_logger.info(f"     {key}: {value}")
            debug_logger.info("=" * 60)
            
            return response
            
        except Exception as e:
            # Log any errors
            process_time = time.time() - start_time
            debug_logger.error(f"❌ REQUEST FAILED")
            debug_logger.error(f"   Error: {str(e)}")
            debug_logger.error(f"   Error Type: {type(e).__name__}")
            debug_logger.error(f"   Process Time: {process_time:.3f} seconds")
            debug_logger.error(f"   Traceback:")
            debug_logger.error(traceback.format_exc())
            debug_logger.error("=" * 60)
            raise

# Add network debugging
def debug_network_status():
    import socket
    import subprocess
    
    debug_logger.info("🌐 NETWORK STATUS DEBUG")
    debug_logger.info("-" * 40)
    
    # Check hostname and IP
    try:
        hostname = socket.gethostname()
        debug_logger.info(f"Hostname: {hostname}")
        
        local_ip = socket.gethostbyname(hostname)
        debug_logger.info(f"Local IP: {local_ip}")
    except Exception as e:
        debug_logger.error(f"Hostname/IP error: {e}")
    
    # Check if port 8000 is bound
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', 8000))
        sock.close()
        
        if result == 0:
            debug_logger.info("✅ Port 8000 is accessible locally")
        else:
            debug_logger.warning("⚠️ Port 8000 not accessible locally")
    except Exception as e:
        debug_logger.error(f"Port check error: {e}")
    
    # List network interfaces
    try:
        result = subprocess.run(['ip', 'addr'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            debug_logger.info("Network interfaces:")
            for line in result.stdout.split('\n')[:20]:  # First 20 lines
                if line.strip():
                    debug_logger.info(f"  {line}")
    except:
        debug_logger.warning("Could not get network interfaces")
    
    debug_logger.info("-" * 40)

# Debug your TTS synthesis function
async def debug_synthesize_endpoint(request: Request):
    debug_logger.info("🎤 SYNTHESIZE ENDPOINT CALLED")
    
    try:
        # Get the JSON data
        json_data = await request.json()
        debug_logger.info(f"Received JSON: {json_data}")
        
        # Extract parameters
        text = json_data.get('text', '')
        voice = json_data.get('voice', '')
        mode = json_data.get('mode', '')
        
        debug_logger.info(f"TTS Parameters:")
        debug_logger.info(f"  Text: '{text[:100]}...' (length: {len(text)})")
        debug_logger.info(f"  Voice: {voice}")
        debug_logger.info(f"  Mode: {mode}")
        
        # Here you would call your actual TTS function
        debug_logger.info("🔊 Starting TTS generation...")
        
        # Simulate TTS processing
        import asyncio
        await asyncio.sleep(0.1)  # Small delay to simulate processing
        
        debug_logger.info("✅ TTS generation completed")
        
        return {
            "status": "success",
            "text_length": len(text),
            "voice": voice,
            "mode": mode
        }
        
    except Exception as e:
        debug_logger.error(f"❌ SYNTHESIZE ERROR: {str(e)}")
        debug_logger.error(f"Traceback: {traceback.format_exc()}")
        raise

# Instructions to add to your main FastAPI app:
"""
In your main.py or app.py, add these lines:

from debug_middleware import TTSDebugMiddleware, debug_network_status, debug_synthesize_endpoint
from fastapi import FastAPI

app = FastAPI()

# Add the debug middleware
app.add_middleware(TTSDebugMiddleware)

# Add debug network status on startup
@app.on_event("startup")
async def startup_debug():
    debug_logger.info("🚀 TTS SERVICE STARTING WITH FULL DEBUG MODE")
    debug_network_status()
    debug_logger.info("🔍 All incoming requests will be logged in detail")

# Replace or enhance your synthesize endpoint
@app.post("/synthesize")
async def synthesize(request: Request):
    return await debug_synthesize_endpoint(request)

@app.get("/health")
async def health():
    debug_logger.info("💚 HEALTH CHECK ENDPOINT HIT")
    return {"status": "healthy", "debug": "enabled"}
"""