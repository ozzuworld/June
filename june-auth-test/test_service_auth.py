#!/usr/bin/env python3
"""
Service-to-Service Authentication Test Suite for June Microservices
Tests the OAuth 2.0 Client Credentials flow between services via Keycloak
"""

import os
import sys
import json
import time
import base64
import asyncio
import argparse
from typing import Dict, Any, Optional
from dataclasses import dataclass

import httpx
import jwt
from dotenv import load_dotenv

load_dotenv()

@dataclass
class ServiceConfig:
    name: str
    base_url: str
    client_id: str
    client_secret: str
    test_endpoints: list

@dataclass
class TestResult:
    service: str
    endpoint: str
    method: str
    success: bool
    status_code: Optional[int] = None
    response_time: Optional[float] = None
    error: Optional[str] = None
    response_data: Optional[Dict] = None

class ServiceAuthTester:
    def __init__(self, keycloak_url: str, realm: str = "june"):
        self.keycloak_url = keycloak_url.rstrip('/')
        self.realm = realm
        self.token_cache: Dict[str, Dict] = {}
        
    async def get_service_token(self, client_id: str, client_secret: str) -> str:
        """Get OAuth 2.0 access token for service"""
        cache_key = f"{client_id}:{client_secret}"
        
        # Check cache first
        if cache_key in self.token_cache:
            token_data = self.token_cache[cache_key]
            if time.time() < token_data['expires_at'] - 30:  # 30s buffer
                return token_data['token']
        
        # Get new token
        token_url = f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect/token"
        
        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "openid profile"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0
            )
            response.raise_for_status()
            
            token_data = response.json()
            expires_in = token_data.get("expires_in", 3600)
            
            # Cache the token
            self.token_cache[cache_key] = {
                'token': token_data["access_token"],
                'expires_at': time.time() + expires_in
            }
            
            return token_data["access_token"]
    
    def decode_token(self, token: str) -> Dict[str, Any]:
        """Decode JWT token (without verification for inspection)"""
        try:
            # Decode without verification for testing purposes
            return jwt.decode(token, options={"verify_signature": False})
        except Exception as e:
            return {"error": str(e)}
    
    async def test_endpoint(
        self, 
        service_config: ServiceConfig, 
        endpoint: str, 
        method: str = "GET",
        data: Optional[Dict] = None
    ) -> TestResult:
        """Test a specific service endpoint with authentication"""
        start_time = time.time()
        
        try:
            # Get service token
            token = await self.get_service_token(
                service_config.client_id, 
                service_config.client_secret
            )
            
            # Make request
            url = f"{service_config.base_url.rstrip('/')}{endpoint}"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method.upper() == "GET":
                    response = await client.get(url, headers=headers)
                elif method.upper() == "POST":
                    response = await client.post(url, headers=headers, json=data or {})
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                response_time = time.time() - start_time
                
                # Try to parse JSON response
                try:
                    response_data = response.json()
                except:
                    response_data = {"raw_response": response.text[:500]}
                
                return TestResult(
                    service=service_config.name,
                    endpoint=endpoint,
                    method=method,
                    success=response.status_code < 400,
                    status_code=response.status_code,
                    response_time=response_time,
                    response_data=response_data
                )
                
        except Exception as e:
            response_time = time.time() - start_time
            return TestResult(
                service=service_config.name,
                endpoint=endpoint,
                method=method,
                success=False,
                response_time=response_time,
                error=str(e)
            )
    
    async def test_service_connectivity(self, services: Dict[str, ServiceConfig]) -> Dict[str, list]:
        """Test connectivity between all services"""
        results = {}
        
        for service_name, config in services.items():
            print(f"\n🧪 Testing {service_name}...")
            service_results = []
            
            for endpoint_info in config.test_endpoints:
                if isinstance(endpoint_info, str):
                    endpoint = endpoint_info
                    method = "GET"
                    data = None
                else:
                    endpoint = endpoint_info.get("path")
                    method = endpoint_info.get("method", "GET")
                    data = endpoint_info.get("data")
                
                result = await self.test_endpoint(config, endpoint, method, data)
                service_results.append(result)
                
                # Print result
                status = "✅" if result.success else "❌"
                print(f"  {status} {method} {endpoint} - {result.status_code} ({result.response_time:.2f}s)")
                
                if not result.success:
                    if result.error:
                        print(f"    Error: {result.error}")
                    elif result.response_data:
                        print(f"    Response: {json.dumps(result.response_data, indent=4)[:200]}")
            
            results[service_name] = service_results
        
        return results
    
    async def test_cross_service_calls(self, services: Dict[str, ServiceConfig]):
        """Test that services can call each other"""
        print(f"\n🔄 Testing cross-service communication...")
        
        # Test Orchestrator calling STT and TTS
        orchestrator = services.get("orchestrator")
        if not orchestrator:
            print("❌ Orchestrator service not configured")
            return
        
        # Test audio processing endpoint (STT -> LLM -> TTS)
        test_audio_data = base64.b64encode(b"fake_audio_data_for_testing").decode()
        
        result = await self.test_endpoint(
            orchestrator,
            "/v1/process-audio",
            "POST",
            {"audio_data": test_audio_data}
        )
        
        status = "✅" if result.success else "❌"
        print(f"  {status} Orchestrator audio processing - {result.status_code}")
        
        if result.response_data:
            print(f"    Response: {json.dumps(result.response_data, indent=2)[:300]}")

def load_service_configs() -> Dict[str, ServiceConfig]:
    """Load service configurations from environment"""
    services = {}
    
    # Define service endpoints to test
    service_endpoints = {
        "orchestrator": [
            "/healthz",
            "/configz", 
            {"path": "/v1/chat", "method": "POST", "data": {"user_input": "Hello, test message"}},
            "/v1/test-auth"
        ],
        "stt": [
            "/healthz",
            "/v1/test-auth"
        ],
        "tts": [
            "/healthz", 
            "/v1/test-auth"
        ]
    }
    
    # Load from environment
    base_configs = {
        "orchestrator": {
            "base_url": os.getenv("ORCHESTRATOR_URL", "https://june-orchestrator-359243954.us-central1.run.app"),
            "client_id": os.getenv("ORCHESTRATOR_CLIENT_ID"),
            "client_secret": os.getenv("ORCHESTRATOR_CLIENT_SECRET")
        },
        "stt": {
            "base_url": os.getenv("STT_URL", "https://june-stt-359243954.us-central1.run.app"),
            "client_id": os.getenv("STT_CLIENT_ID"),
            "client_secret": os.getenv("STT_CLIENT_SECRET")
        },
        "tts": {
            "base_url": os.getenv("TTS_URL", "https://june-tts-359243954.us-central1.run.app"),
            "client_id": os.getenv("TTS_CLIENT_ID"),
            "client_secret": os.getenv("TTS_CLIENT_SECRET")
        }
    }
    
    for service_name, config in base_configs.items():
        if config["client_id"] and config["client_secret"]:
            services[service_name] = ServiceConfig(
                name=service_name,
                base_url=config["base_url"],
                client_id=config["client_id"],
                client_secret=config["client_secret"],
                test_endpoints=service_endpoints.get(service_name, ["/healthz"])
            )
        else:
            print(f"⚠️  Skipping {service_name} - missing credentials")
    
    return services

async def test_keycloak_connectivity(keycloak_url: str, realm: str = "june"):
    """Test basic Keycloak connectivity"""
    print("🔐 Testing Keycloak connectivity...")
    
    # Test realm info endpoint
    realm_url = f"{keycloak_url}/realms/{realm}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(realm_url, timeout=10.0)
            response.raise_for_status()
            
            realm_info = response.json()
            print(f"✅ Keycloak realm '{realm}' accessible")
            print(f"   Issuer: {realm_info.get('issuer')}")
            print(f"   Token endpoint: {realm_info.get('token-service')}")
            
            return True
            
    except Exception as e:
        print(f"❌ Keycloak connectivity failed: {e}")
        return False

def print_summary(results: Dict[str, list]):
    """Print test summary"""
    print(f"\n📊 Test Summary")
    print("=" * 50)
    
    total_tests = 0
    passed_tests = 0
    
    for service_name, service_results in results.items():
        service_passed = sum(1 for r in service_results if r.success)
        service_total = len(service_results)
        
        total_tests += service_total
        passed_tests += service_passed
        
        print(f"{service_name}: {service_passed}/{service_total} passed")
        
        # Show failed tests
        failed = [r for r in service_results if not r.success]
        if failed:
            for failure in failed:
                print(f"  ❌ {failure.method} {failure.endpoint}: {failure.error or f'HTTP {failure.status_code}'}")
    
    print(f"\nOverall: {passed_tests}/{total_tests} tests passed ({passed_tests/total_tests*100:.1f}%)")

async def main():
    parser = argparse.ArgumentParser(description="Test June microservices authentication")
    parser.add_argument("--keycloak-url", default=os.getenv("KC_BASE_URL", "http://localhost:8080"))
    parser.add_argument("--realm", default=os.getenv("KC_REALM", "june"))
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--token-info", action="store_true", help="Show token information")
    
    args = parser.parse_args()
    
    print("🚀 June Microservices Authentication Test Suite")
    print("=" * 50)
    
    # Test Keycloak first
    keycloak_ok = await test_keycloak_connectivity(args.keycloak_url, args.realm)
    if not keycloak_ok:
        print("❌ Cannot proceed without Keycloak connectivity")
        sys.exit(1)
    
    # Load service configurations
    services = load_service_configs()
    if not services:
        print("❌ No services configured. Please set environment variables:")
        print("   ORCHESTRATOR_CLIENT_ID, ORCHESTRATOR_CLIENT_SECRET")
        print("   STT_CLIENT_ID, STT_CLIENT_SECRET") 
        print("   TTS_CLIENT_ID, TTS_CLIENT_SECRET")
        sys.exit(1)
    
    print(f"\n📋 Configured services: {', '.join(services.keys())}")
    
    # Create tester
    tester = ServiceAuthTester(args.keycloak_url, args.realm)
    
    # Show token info if requested
    if args.token_info:
        print(f"\n🎫 Token Information")
        for service_name, config in services.items():
            try:
                token = await tester.get_service_token(config.client_id, config.client_secret)
                decoded = tester.decode_token(token)
                print(f"\n{service_name}:")
                print(f"  Client ID: {config.client_id}")
                print(f"  Subject: {decoded.get('sub', 'N/A')}")
                print(f"  Scopes: {decoded.get('scope', 'N/A')}")
                print(f"  Expires: {decoded.get('exp', 'N/A')}")
                print(f"  Issuer: {decoded.get('iss', 'N/A')}")
            except Exception as e:
                print(f"  ❌ Failed to get token: {e}")
    
    # Run connectivity tests
    results = await tester.test_service_connectivity(services)
    
    # Test cross-service calls
    await tester.test_cross_service_calls(services)
    
    # Print summary
    print_summary(results)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        sys.exit(1)