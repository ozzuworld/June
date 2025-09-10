#!/usr/bin/env python3
"""
Diagnostic script to understand nginx-edge routing vs direct service access
"""

import asyncio
import httpx
import json

async def test_with_details(name: str, url: str):
    """Test endpoint and show full response details"""
    print(f"\n🧪 Testing {name}: {url}")
    
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.get(url)
            
            print(f"   Status: {response.status_code}")
            print(f"   Headers: {dict(response.headers)}")
            
            # Show content type and preview
            content_type = response.headers.get('content-type', 'unknown')
            print(f"   Content-Type: {content_type}")
            
            if 'html' in content_type.lower():
                print(f"   Content (HTML): {response.text[:200]}...")
            elif 'json' in content_type.lower():
                try:
                    data = response.json()
                    print(f"   Content (JSON): {json.dumps(data, indent=2)}")
                except:
                    print(f"   Content (Raw): {response.text[:200]}")
            else:
                print(f"   Content: {response.text[:200]}")
                
    except Exception as e:
        print(f"   ❌ Error: {e}")

async def main():
    print("🔍 Nginx Routing Diagnostic")
    print("=" * 50)
    
    # Test 1: nginx-edge itself
    await test_with_details("nginx-edge health", "https://nginx-edge-359243954.us-central1.run.app/healthz")
    await test_with_details("nginx-edge root", "https://nginx-edge-359243954.us-central1.run.app/")
    
    # Test 2: Direct service access (bypassing nginx-edge)
    print(f"\n📡 Direct Service Access (bypassing nginx-edge):")
    await test_with_details("orchestrator direct", "https://june-orchestrator-359243954.us-central1.run.app/")
    await test_with_details("orchestrator direct healthz", "https://june-orchestrator-359243954.us-central1.run.app/healthz")
    
    # Test 3: Through nginx-edge routing
    print(f"\n🔄 Through nginx-edge routing:")
    await test_with_details("orchestrator via nginx", "https://nginx-edge-359243954.us-central1.run.app/orchestrator/")
    await test_with_details("orchestrator health via nginx", "https://nginx-edge-359243954.us-central1.run.app/orchestrator/healthz")
    
    # Test 4: Keycloak (we know this works)
    await test_with_details("keycloak direct", "https://june-idp-359243954.us-central1.run.app/realms/june")
    await test_with_details("keycloak via nginx", "https://nginx-edge-359243954.us-central1.run.app/auth/realms/june")
    
    print(f"\n📊 Analysis:")
    print("1. If nginx-edge /healthz works → nginx is running")
    print("2. If direct service access works → services are running") 
    print("3. If nginx routing fails → routing configuration issue")
    print("4. If all fail → need to check service deployment")

if __name__ == "__main__":
    asyncio.run(main())