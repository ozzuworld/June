#!/usr/bin/env python3
"""
Test with the CORRECT endpoints based on your actual service code
"""

import asyncio
import httpx
import json
import time

# Direct service URLs
SERVICES = {
    "orchestrator": "https://june-orchestrator-359243954.us-central1.run.app",
    "stt": "https://june-stt-359243954.us-central1.run.app", 
    "tts": "https://june-tts-359243954.us-central1.run.app",
    "idp": "https://june-idp-359243954.us-central1.run.app"
}

# nginx-edge URLs
NGINX_EDGE = "https://nginx-edge-359243954.us-central1.run.app"

async def test_endpoint(name: str, url: str, endpoint: str):
    """Test a single endpoint"""
    full_url = f"{url.rstrip('/')}{endpoint}"
    start_time = time.time()
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(full_url)
            duration = time.time() - start_time
            
            status = "✅" if response.status_code < 400 else "❌"
            print(f"{status} {name:12} {endpoint:20} -> {response.status_code} ({duration:.2f}s)")
            
            if response.status_code < 400:
                try:
                    data = response.json()
                    if isinstance(data, dict) and len(str(data)) < 200:
                        print(f"   Response: {data}")
                except:
                    pass
            elif response.status_code == 404:
                print(f"   ❓ Endpoint not found")
            elif response.status_code == 401:
                print(f"   🔒 Protected (expected)")
            else:
                print(f"   Error: {response.text[:50]}...")
                
            return response.status_code < 400
            
    except Exception as e:
        duration = time.time() - start_time
        print(f"❌ {name:12} {endpoint:20} -> ERROR ({duration:.2f}s)")
        print(f"   Exception: {str(e)[:50]}...")
        return False

async def main():
    print("🚀 Testing with CORRECT endpoints")
    print("=" * 60)
    
    print("\n📡 Testing DIRECT service access:")
    print("   (Based on your actual FastAPI code)")
    
    # Test endpoints that actually exist in your code
    test_cases = [
        # Orchestrator endpoints (from app.py)
        ("orchestrator", SERVICES["orchestrator"], "/healthz"),
        ("orchestrator", SERVICES["orchestrator"], "/configz"),
        ("orchestrator", SERVICES["orchestrator"], "/v1/chat"),
        ("orchestrator", SERVICES["orchestrator"], "/v1/process-audio"),
        ("orchestrator", SERVICES["orchestrator"], "/v1/test-auth"),
        
        # STT endpoints (from app.py)
        ("stt", SERVICES["stt"], "/healthz"),
        ("stt", SERVICES["stt"], "/v1/test-auth"),
        ("stt", SERVICES["stt"], "/v1/transcribe"),
        
        # TTS endpoints (from app.py)  
        ("tts", SERVICES["tts"], "/healthz"),
        ("tts", SERVICES["tts"], "/v1/test-auth"),
        ("tts", SERVICES["tts"], "/v1/tts"),
        
        # Keycloak endpoints (known to work)
        ("idp", SERVICES["idp"], "/realms/june"),
        ("idp", SERVICES["idp"], "/health"),
        ("idp", SERVICES["idp"], "/health/ready"),
    ]
    
    for service_name, base_url, endpoint in test_cases:
        await test_endpoint(service_name, base_url, endpoint)
    
    print(f"\n🔄 Testing through nginx-edge:")
    print("   (Same endpoints but through reverse proxy)")
    
    # Test through nginx-edge
    nginx_test_cases = [
        ("nginx-edge", NGINX_EDGE, "/healthz"),
        ("nginx-edge", NGINX_EDGE, "/"),
        ("nginx-edge", NGINX_EDGE, "/auth/realms/june"),
        ("nginx-edge", NGINX_EDGE, "/orchestrator/healthz"),
        ("nginx-edge", NGINX_EDGE, "/orchestrator/configz"),
        ("nginx-edge", NGINX_EDGE, "/stt/healthz"),
        ("nginx-edge", NGINX_EDGE, "/tts/healthz"),
    ]
    
    for service_name, base_url, endpoint in nginx_test_cases:
        await test_endpoint(service_name, base_url, endpoint)
    
    print(f"\n📊 ANALYSIS:")
    print("=" * 40)
    print("Looking at your FastAPI code:")
    print("✅ All services SHOULD have /healthz endpoints")
    print("✅ Keycloak realm works (proves services are running)")
    print("❓ If /healthz returns 404, check your FastAPI route definitions")
    
    print(f"\n🔧 LIKELY ISSUES:")
    print("1. FastAPI services missing @app.get('/healthz') routes")
    print("2. Services might use different health check paths")
    print("3. nginx-edge routing might have path issues")
    
    print(f"\n🎯 NEXT STEPS:")
    print("1. Check which endpoints actually work above")
    print("2. Add missing /healthz routes to FastAPI services")
    print("3. Test nginx-edge routing once direct endpoints work")

if __name__ == "__main__":
    asyncio.run(main())