#!/usr/bin/env python3
"""
WebSocket Connection Diagnostic Tool
Checks connectivity issues step by step
"""

import asyncio
import ssl
import socket
import websockets
import httpx
import logging
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
API_URL = "https://api.ozzu.world"
WS_URL = "wss://api.ozzu.world/ws"
TEST_TOKEN = ".eyJleHAiOjE3NjAyMDg2MDYsImlhdCI6MTc2MDIwNTAwNiwiYXV0aF90aW1lIjoxNzYwMjA1MDA2LCJqdGkiOiJvbnJ0YWM6YjY3NDRkMDktNGRhMS1lNDU0LTI5MTAtYTA1NmU0NDliNjBkIiwiaXNzIjoiaHR0cHM6Ly9pZHAub3p6dS53b3JsZC9yZWFsbXMvYWxsc2FmZSIsImF1ZCI6WyJqdW5lLW9yY2hlc3RyYXRvciIsImFjY291bnQiXSwic3ViIjoiZmY1ZDRmYjUtY2Q0NS00NGJkLWE0MjUtOGJjZmVkZGExYWEzIiwidHlwIjoiQmVhcmVyIiwiYXpwIjoianVuZS1tb2JpbGUtYXBwIiwic2lkIjoiYTQ2ZGU3ZjgtNjg3My01ZDg5LWQyMDMtMWZlYjRhNzg2YmEyIiwiYWNyIjoiMSIsInJlYWxtX2FjY2VzcyI6eyJyb2xlcyI6WyJvZmZsaW5lX2FjY2VzcyIsInVtYV9hdXRob3JpemF0aW9uIiwiZGVmYXVsdC1yb2xlcy1hbGxzYWZlIl19LCJyZXNvdXJjZV9hY2Nlc3MiOnsiYWNjb3VudCI6eyJyb2xlcyI6WyJtYW5hZ2UtYWNjb3VudCIsIm1hbmFnZS1hY2NvdW50LWxpbmtzIiwidmlldy1wcm9maWxlIl19fSwic2NvcGUiOiJvcGVuaWQgb3JjaGVzdHJhdG9yLWF1ZCBwcm9maWxlIGVtYWlsIiwiZW1haWxfdmVyaWZpZWQiOmZhbHNlLCJuYW1lIjoidGVzdCB0ZXN0IiwicHJlZmVycmVkX3VzZXJuYW1lIjoidGVzdCIsImdpdmVuX25hbWUiOiJ0ZXN0IiwiZmFtaWx5X25hbWUiOiJ0ZXN0IiwiZW1haWwiOiJ0ZXN0QHRlc3QuY29tIn0.hOq4jcSAiUkBMAGiJYD2RBo3LbDiRQJo-jupN_wDoYAJ3EYVYCxgKXT5BuqS5wNArJ0QQp-0BsxXGDYCDrTAL1NmViEb7BhrruZm0eyh4BJZvZfCT4lLuKL8LwgWln-rm13s6Zr9LnRYtNcUcwNiUseTp9vJsEfDCYQ8qkr8hzaGMK94Cr-kZenKIECggBOoMaorra9mgiCVmnHeFPLnX4_Pl0dsAXhXpGTispfiIG0H0w7-6RIN3U9uhSrQHoVzA0QbCYDzunw5tDbobXtue54GjDQvuNVXL7SrKra8XT-9AUJ27LjMa8M_zynaFLm43clQfyZTDzwgRQXDvEQc5A"


async def test_step_1_dns():
    """Test DNS resolution"""
    logger.info("Step 1: DNS Resolution")
    logger.info("-" * 50)
    
    try:
        domain = urlparse(API_URL).netloc
        ip = socket.gethostbyname(domain)
        logger.info(f"✅ DNS resolved: {domain} → {ip}")
        return True
    except Exception as e:
        logger.error(f"❌ DNS resolution failed: {e}")
        return False


async def test_step_2_https():
    """Test HTTPS connectivity"""
    logger.info("\nStep 2: HTTPS Connectivity")
    logger.info("-" * 50)
    
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
            response = await client.get(f"{API_URL}/healthz")
            
            if response.status_code == 200:
                logger.info(f"✅ HTTPS working: {response.status_code}")
                data = response.json()
                logger.info(f"   Service: {data.get('service', 'unknown')}")
                logger.info(f"   Version: {data.get('version', 'unknown')}")
                return True
            else:
                logger.warning(f"⚠️  HTTPS returned: {response.status_code}")
                return False
                
    except Exception as e:
        logger.error(f"❌ HTTPS connection failed: {e}")
        return False


async def test_step_3_websocket_basic():
    """Test basic WebSocket without token"""
    logger.info("\nStep 3: WebSocket Basic Connection")
    logger.info("-" * 50)
    
    # Try connecting without token first
    try:
        logger.info(f"Attempting: {WS_URL} (no token)")
        
        async with websockets.connect(
            WS_URL,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
            open_timeout=10  # Explicit timeout
        ) as ws:
            logger.info("✅ WebSocket connected (no auth)")
            
            # Try to receive a message
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                logger.info(f"   Response: {msg[:100]}...")
                return True
            except asyncio.TimeoutError:
                logger.info("   No immediate response (might require auth)")
                return True
                
    except websockets.exceptions.InvalidStatusCode as e:
        logger.warning(f"⚠️  WebSocket rejected: {e.status_code}")
        logger.info("   This is expected if auth is required")
        return True  # Connection attempt worked, just rejected
        
    except asyncio.TimeoutError:
        logger.error("❌ WebSocket connection TIMEOUT")
        logger.error("   The server is not responding to WebSocket upgrade")
        return False
        
    except Exception as e:
        logger.error(f"❌ WebSocket connection failed: {e}")
        logger.error(f"   Error type: {type(e).__name__}")
        return False


async def test_step_4_websocket_with_token():
    """Test WebSocket with token"""
    logger.info("\nStep 4: WebSocket with Token")
    logger.info("-" * 50)
    
    try:
        url_with_token = f"{WS_URL}?token={TEST_TOKEN}"
        logger.info(f"Attempting: {WS_URL}?token=...")
        
        async with websockets.connect(
            url_with_token,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
            open_timeout=10
        ) as ws:
            logger.info("✅ WebSocket connected with token")
            
            # Wait for connection message
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                import json
                data = json.loads(msg)
                
                logger.info(f"   Message type: {data.get('type')}")
                
                if data.get('type') == 'connected':
                    logger.info(f"   Session: {data.get('session_id', 'N/A')[:8]}...")
                    logger.info(f"   WebRTC: {data.get('webrtc_enabled', False)}")
                    return True
                else:
                    logger.warning(f"   Unexpected: {data}")
                    return False
                    
            except asyncio.TimeoutError:
                logger.error("❌ No response from server")
                return False
                
    except asyncio.TimeoutError:
        logger.error("❌ WebSocket connection TIMEOUT with token")
        return False
        
    except Exception as e:
        logger.error(f"❌ WebSocket failed: {e}")
        logger.error(f"   Error type: {type(e).__name__}")
        return False


async def test_step_5_check_ingress():
    """Check ingress configuration"""
    logger.info("\nStep 5: Ingress Configuration Check")
    logger.info("-" * 50)
    
    try:
        # Check if WebSocket upgrade headers work
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                API_URL,
                headers={
                    "Upgrade": "websocket",
                    "Connection": "Upgrade"
                }
            )
            
            logger.info(f"HTTP response: {response.status_code}")
            
            # Check for WebSocket support headers
            if "upgrade" in response.headers:
                logger.info(f"✅ Upgrade header: {response.headers.get('upgrade')}")
            else:
                logger.warning("⚠️  No upgrade header in response")
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Ingress check failed: {e}")
        return False


async def test_step_6_backend_logs():
    """Suggest checking backend logs"""
    logger.info("\nStep 6: Backend Health")
    logger.info("-" * 50)
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{API_URL}/status")
            
            if response.status_code == 200:
                data = response.json()
                logger.info("✅ Backend status:")
                logger.info(f"   Connections: {data.get('websocket_connections', 0)}")
                logger.info(f"   WebRTC enabled: {data.get('webrtc_enabled', False)}")
                logger.info(f"   Version: {data.get('version', 'unknown')}")
                return True
            else:
                logger.warning(f"⚠️  Status endpoint: {response.status_code}")
                return False
                
    except Exception as e:
        logger.error(f"❌ Status check failed: {e}")
        return False


async def main():
    """Run all diagnostic tests"""
    
    logger.info("="*70)
    logger.info("🔍 WebSocket Connection Diagnostics")
    logger.info("="*70)
    logger.info("")
    
    results = {}
    
    # Run tests sequentially
    results['dns'] = await test_step_1_dns()
    results['https'] = await test_step_2_https()
    results['websocket_basic'] = await test_step_3_websocket_basic()
    results['websocket_token'] = await test_step_4_websocket_with_token()
    results['ingress'] = await test_step_5_check_ingress()
    results['backend'] = await test_step_6_backend_logs()
    
    # Print summary
    logger.info("\n" + "="*70)
    logger.info("📊 Diagnostic Summary")
    logger.info("="*70)
    logger.info("")
    
    for test, passed in results.items():
        status = "✅" if passed else "❌"
        logger.info(f"{status} {test.replace('_', ' ').title()}")
    
    logger.info("")
    
    # Diagnosis
    if all(results.values()):
        logger.info("✅ ALL CHECKS PASSED - WebSocket should work!")
        logger.info("")
        logger.info("If you're still having issues:")
        logger.info("  1. Try a different network")
        logger.info("  2. Check if VPN/proxy is interfering")
        logger.info("  3. Test from browser: chrome://inspect/#devices")
        
    elif not results['dns']:
        logger.error("❌ DNS ISSUE")
        logger.error("")
        logger.error("Cannot resolve api.ozzu.world")
        logger.error("Fix:")
        logger.error("  1. Check internet connection")
        logger.error("  2. Try: ping api.ozzu.world")
        logger.error("  3. Check DNS settings")
        
    elif not results['https']:
        logger.error("❌ HTTPS CONNECTIVITY ISSUE")
        logger.error("")
        logger.error("Cannot connect to HTTPS endpoint")
        logger.error("Possible causes:")
        logger.error("  • Firewall blocking HTTPS")
        logger.error("  • Backend service down")
        logger.error("  • Certificate issues")
        
    elif not results['websocket_basic']:
        logger.error("❌ WEBSOCKET TIMEOUT")
        logger.error("")
        logger.error("WebSocket upgrade is timing out")
        logger.error("")
        logger.error("Most likely causes:")
        logger.error("  1. Ingress not configured for WebSocket")
        logger.error("  2. WebSocket timeout too short")
        logger.error("  3. Backend not handling /ws endpoint")
        logger.error("")
        logger.error("Check ingress annotations:")
        logger.error("  kubectl get ingress june-ingress -n june-services -o yaml")
        logger.error("")
        logger.error("Should have:")
        logger.error('  nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"')
        logger.error('  nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"')
        logger.error('  nginx.ingress.kubernetes.io/websocket-services: "june-orchestrator"')
        
    elif not results['websocket_token']:
        logger.error("❌ WEBSOCKET WITH TOKEN FAILED")
        logger.error("")
        logger.error("WebSocket connects but token is rejected")
        logger.error("Check:")
        logger.error("  • Token format")
        logger.error("  • Backend auth validation")
        
    elif not results['backend']:
        logger.warning("⚠️  BACKEND STATUS UNAVAILABLE")
        logger.warning("")
        logger.warning("Cannot get backend status")
        logger.warning("Backend might be overloaded or restarting")
    
    logger.info("")
    logger.info("="*70)


if __name__ == "__main__":
    asyncio.run(main())