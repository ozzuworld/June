#!/usr/bin/env python3
"""
Quick test script to check if your deployed services are responding
Run this first to verify basic connectivity before testing authentication
"""

import asyncio
import httpx
import json
import time

# Your current service URLs from the codebase
SERVICES = {
    "orchestrator": "https://june-orchestrator-359243954.us-central1.run.app",
    "stt": "https://june-stt-359243954.us-central1.run.app", 
    "tts": "https://june-tts-359243954.us-central1.run.app",
    "idp": "https://june-idp-359243954.us-central1.run.app"
}

async def test_endpoint(name: str, url: str, endpoint: str = "/healthz"):
    """Test a single endpoint"""
    full_url = f"{url.rstrip('/')}{endpoint}"
    start_time = time.time()
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(full_url)
            duration = time.time() - start_time
            
            status = "✅" if response.status_code < 400 else "❌"
            print(f"{status} {name:12} {endpoint:15} -> {response.status_code} ({duration:.2f}s)")
            
            if response.status_code < 400:
                try:
                    data = response.json()
                    if isinstance(data, dict) and len(str(data)) < 200:
                        print(f"   Response: {data}")
                except:
                    pass
            else:
                print(f"   Error: {response.text[:100]}")
                
            return response.status_code < 400
            
    except Exception as e:
        duration = time.time() - start_time
        print(f"❌ {name:12} {endpoint:15} -> ERROR ({duration:.2f}s)")
        print(f"   Exception: {str(e)[:100]}")
        return False

async def test_keycloak_realm():
    """Test Keycloak realm info endpoint"""
    idp_url = SERVICES.get("idp", "")
    if not idp_url:
        print("❌ No IDP URL configured")
        return False
    
    # Try different realm endpoints
    test_urls = [
        f"{idp_url}/realms/june",
        f"{idp_url}/auth/realms/june", 
        f"{idp_url}/realms/june/.well-known/openid_configuration"
    ]
    
    print("\n🔐 Testing Keycloak realm endpoints...")
    
    for url in test_urls:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    print(f"✅ Keycloak realm accessible at: {url}")
                    try:
                        data = response.json()
                        if "issuer" in data:
                            print(f"   Issuer: {data['issuer']}")
                        if "token_endpoint" in data:
                            print(f"   Token endpoint: {data['token_endpoint']}")
                    except:
                        pass
                    return True
                else:
                    print(f"❌ {url} -> {response.status_code}")
        except Exception as e:
            print(f"❌ {url} -> {str(e)[:50]}")
    
    return False

async def test_service_auth_endpoints():
    """Test the /v1/test-auth endpoints that should require service authentication"""
    print(f"\n🔒 Testing protected endpoints (should return 401 without auth)...")
    
    test_endpoints = [
        ("orchestrator", "/v1/test-auth"),
        ("stt", "/v1/test-auth"), 
        ("tts", "/v1/test-auth")
    ]
    
    for service_name, endpoint in test_endpoints:
        url = SERVICES.get(service_name)
        if url:
            full_url = f"{url.rstrip('/')}{endpoint}"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(full_url)
                    
                    if response.status_code == 401:
                        print(f"✅ {service_name:12} {endpoint:15} -> 401 (correctly protected)")
                    elif response.status_code == 404:
                        print(f"⚠️  {service_name:12} {endpoint:15} -> 404 (endpoint not found)")
                    else:
                        print(f"❓ {service_name:12} {endpoint:15} -> {response.status_code} (unexpected)")
                        
            except Exception as e:
                print(f"❌ {service_name:12} {endpoint:15} -> ERROR: {str(e)[:50]}")

async def main():
    print("🚀 Quick Service Connectivity Test")
    print("=" * 50)
    
    # Test basic health endpoints
    print("📡 Testing basic connectivity...")
    healthy_services = []
    
    for name, url in SERVICES.items():
        if await test_endpoint(name, url, "/healthz"):
            healthy_services.append(name)
    
    print(f"\n✅ Healthy services: {len(healthy_services)}/{len(SERVICES)}")
    print(f"   Services: {', '.join(healthy_services)}")
    
    # Test additional endpoints
    if "orchestrator" in healthy_services:
        await test_endpoint("orchestrator", SERVICES["orchestrator"], "/configz")
    
    # Test Keycloak realm
    await test_keycloak_realm()
    
    # Test protected endpoints
    await test_service_auth_endpoints()
    
    print(f"\n📋 Next Steps:")
    print("1. Ensure all services are healthy (showing ✅)")
    print("2. Verify Keycloak realm is accessible") 
    print("3. Set up service clients in Keycloak admin console")
    print("4. Run the full authentication test suite")
    
    if len(healthy_services) == len(SERVICES):
        print(f"\n🎉 All services are responding! Ready for authentication testing.")
    else:
        failed = set(SERVICES.keys()) - set(healthy_services)
        print(f"\n⚠️  Fix connectivity issues with: {', '.join(failed)}")

if __name__ == "__main__":
    asyncio.run(main())