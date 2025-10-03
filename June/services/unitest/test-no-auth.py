#!/usr/bin/env python3
"""
June Services Integration Tests
Tests all services: IDP, Orchestrator, STT, TTS
"""

import asyncio
import httpx
import json
import sys
from typing import Dict, Any, Optional
from datetime import datetime
import base64
from pathlib import Path

# Service URLs
SERVICES = {
    "idp": "https://idp.allsafe.world",
    "api": "https://api.allsafe.world",
    "tts": "https://tts.allsafe.world",
    "stt": "https://stt.allsafe.world"
}

# Test results storage
test_results = {
    "passed": 0,
    "failed": 0,
    "skipped": 0,
    "tests": []
}

# ANSI color codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"


def log_test(name: str, status: str, message: str = "", details: Any = None):
    """Log test result"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    if status == "PASS":
        color = GREEN
        symbol = "✓"
        test_results["passed"] += 1
    elif status == "FAIL":
        color = RED
        symbol = "✗"
        test_results["failed"] += 1
    else:  # SKIP
        color = YELLOW
        symbol = "⊘"
        test_results["skipped"] += 1
    
    print(f"{color}[{timestamp}] {symbol} {name}{RESET}")
    if message:
        print(f"  {message}")
    
    test_results["tests"].append({
        "name": name,
        "status": status,
        "message": message,
        "details": details,
        "timestamp": timestamp
    })


class ServiceTester:
    """Base class for service testing"""
    
    def __init__(self, base_url: str, service_name: str):
        self.base_url = base_url
        self.service_name = service_name
        self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        self.token: Optional[str] = None
    
    async def close(self):
        await self.client.aclose()
    
    async def test_connectivity(self) -> bool:
        """Test basic connectivity"""
        test_name = f"{self.service_name} - Connectivity"
        try:
            response = await self.client.get(f"{self.base_url}/healthz")
            
            if response.status_code == 200:
                log_test(test_name, "PASS", f"Status: {response.status_code}")
                return True
            else:
                log_test(test_name, "FAIL", f"Status: {response.status_code}")
                return False
        except Exception as e:
            log_test(test_name, "FAIL", f"Error: {str(e)}")
            return False
    
    async def test_health(self) -> bool:
        """Test health endpoint"""
        test_name = f"{self.service_name} - Health Check"
        try:
            response = await self.client.get(f"{self.base_url}/healthz")
            
            if response.status_code == 200:
                data = response.json()
                log_test(test_name, "PASS", 
                        f"Status: {data.get('status', 'unknown')}", 
                        details=data)
                return True
            else:
                log_test(test_name, "FAIL", f"Status: {response.status_code}")
                return False
        except Exception as e:
            log_test(test_name, "FAIL", f"Error: {str(e)}")
            return False


class IDPTester(ServiceTester):
    """Test Keycloak IDP service"""
    
    def __init__(self):
        super().__init__(SERVICES["idp"], "IDP (Keycloak)")
    
    async def test_oidc_discovery(self) -> bool:
        """Test OIDC discovery endpoint"""
        test_name = f"{self.service_name} - OIDC Discovery"
        try:
            url = f"{self.base_url}/realms/allsafe/.well-known/openid-configuration"
            response = await self.client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                required_fields = ["issuer", "authorization_endpoint", 
                                 "token_endpoint", "jwks_uri"]
                
                missing = [f for f in required_fields if f not in data]
                
                if not missing:
                    log_test(test_name, "PASS", 
                            f"Issuer: {data.get('issuer')}")
                    return True
                else:
                    log_test(test_name, "FAIL", 
                            f"Missing fields: {missing}")
                    return False
            else:
                log_test(test_name, "FAIL", f"Status: {response.status_code}")
                return False
        except Exception as e:
            log_test(test_name, "FAIL", f"Error: {str(e)}")
            return False
    
    async def test_jwks(self) -> bool:
        """Test JWKS endpoint"""
        test_name = f"{self.service_name} - JWKS"
        try:
            url = f"{self.base_url}/realms/allsafe/protocol/openid-connect/certs"
            response = await self.client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                keys = data.get("keys", [])
                
                if keys:
                    log_test(test_name, "PASS", 
                            f"Found {len(keys)} signing keys")
                    return True
                else:
                    log_test(test_name, "FAIL", "No signing keys found")
                    return False
            else:
                log_test(test_name, "FAIL", f"Status: {response.status_code}")
                return False
        except Exception as e:
            log_test(test_name, "FAIL", f"Error: {str(e)}")
            return False


class OrchestratorTester(ServiceTester):
    """Test Orchestrator service"""
    
    def __init__(self):
        super().__init__(SERVICES["api"], "Orchestrator")
    
    async def test_info(self) -> bool:
        """Test root info endpoint"""
        test_name = f"{self.service_name} - Service Info"
        try:
            response = await self.client.get(f"{self.base_url}/")
            
            if response.status_code == 200:
                data = response.json()
                log_test(test_name, "PASS", 
                        f"Version: {data.get('version', 'unknown')}", 
                        details=data)
                return True
            else:
                log_test(test_name, "FAIL", f"Status: {response.status_code}")
                return False
        except Exception as e:
            log_test(test_name, "FAIL", f"Error: {str(e)}")
            return False
    
    async def test_chat_basic(self) -> bool:
        """Test basic chat without authentication"""
        test_name = f"{self.service_name} - Basic Chat (Unauthenticated)"
        try:
            payload = {
                "text": "Hello, this is a test",
                "language": "en",
                "temperature": 0.7,
                "max_tokens": 100,
                "include_audio": False
            }
            
            response = await self.client.post(
                f"{self.base_url}/v1/chat",
                json=payload
            )
            
            # May fail with 401 if auth required, which is expected
            if response.status_code == 200:
                data = response.json()
                log_test(test_name, "PASS", 
                        f"Response received: {data.get('message', {}).get('text', '')[:50]}...")
                return True
            elif response.status_code == 401:
                log_test(test_name, "SKIP", 
                        "Authentication required (expected)")
                return True
            else:
                log_test(test_name, "FAIL", 
                        f"Status: {response.status_code}")
                return False
        except Exception as e:
            log_test(test_name, "FAIL", f"Error: {str(e)}")
            return False
    
    async def test_tts_status(self) -> bool:
        """Test TTS status endpoint"""
        test_name = f"{self.service_name} - TTS Status"
        try:
            response = await self.client.get(f"{self.base_url}/v1/tts/status")
            
            if response.status_code == 200:
                data = response.json()
                log_test(test_name, "PASS", 
                        f"TTS Available: {data.get('available', False)}")
                return True
            else:
                log_test(test_name, "FAIL", f"Status: {response.status_code}")
                return False
        except Exception as e:
            log_test(test_name, "FAIL", f"Error: {str(e)}")
            return False


class TTSTester(ServiceTester):
    """Test TTS service"""
    
    def __init__(self):
        super().__init__(SERVICES["tts"], "TTS")
    
    async def test_voices(self) -> bool:
        """Test voices endpoint"""
        test_name = f"{self.service_name} - List Voices"
        try:
            response = await self.client.get(f"{self.base_url}/v1/voices")
            
            if response.status_code == 200:
                data = response.json()
                voices = data.get("voices", [])
                log_test(test_name, "PASS", 
                        f"Found {len(voices)} voices")
                return True
            else:
                log_test(test_name, "FAIL", f"Status: {response.status_code}")
                return False
        except Exception as e:
            log_test(test_name, "FAIL", f"Error: {str(e)}")
            return False
    
    async def test_status(self) -> bool:
        """Test TTS status endpoint"""
        test_name = f"{self.service_name} - Service Status"
        try:
            response = await self.client.get(f"{self.base_url}/v1/status")
            
            if response.status_code == 200:
                data = response.json()
                log_test(test_name, "PASS", 
                        f"Status: {data.get('status', 'unknown')}", 
                        details=data)
                return True
            else:
                log_test(test_name, "FAIL", f"Status: {response.status_code}")
                return False
        except Exception as e:
            log_test(test_name, "FAIL", f"Error: {str(e)}")
            return False
    
    async def test_synthesis_basic(self) -> bool:
        """Test basic TTS synthesis"""
        test_name = f"{self.service_name} - Basic Synthesis"
        try:
            payload = {
                "text": "This is a test.",
                "voice": "default",
                "speed": 1.0,
                "language": "EN",
                "format": "wav"
            }
            
            response = await self.client.post(
                f"{self.base_url}/v1/tts",
                json=payload
            )
            
            if response.status_code == 200:
                audio_size = len(response.content)
                log_test(test_name, "PASS", 
                        f"Generated {audio_size} bytes of audio")
                return True
            elif response.status_code == 401:
                log_test(test_name, "SKIP", 
                        "Authentication required (expected)")
                return True
            else:
                log_test(test_name, "FAIL", 
                        f"Status: {response.status_code}")
                return False
        except Exception as e:
            log_test(test_name, "FAIL", f"Error: {str(e)}")
            return False


class STTTester(ServiceTester):
    """Test STT service"""
    
    def __init__(self):
        super().__init__(SERVICES["stt"], "STT")
    
    async def test_capabilities(self) -> bool:
        """Test capabilities endpoint"""
        test_name = f"{self.service_name} - Capabilities"
        try:
            response = await self.client.get(f"{self.base_url}/")
            
            if response.status_code == 200:
                data = response.json()
                log_test(test_name, "PASS", 
                        f"Whisper Model: {data.get('whisper_model', 'unknown')}", 
                        details=data)
                return True
            else:
                log_test(test_name, "FAIL", f"Status: {response.status_code}")
                return False
        except Exception as e:
            log_test(test_name, "FAIL", f"Error: {str(e)}")
            return False
    
    async def test_ready(self) -> bool:
        """Test readiness endpoint"""
        test_name = f"{self.service_name} - Readiness"
        try:
            response = await self.client.get(f"{self.base_url}/ready")
            
            if response.status_code == 200:
                data = response.json()
                log_test(test_name, "PASS", 
                        f"Model Loaded: {data.get('model_loaded', False)}")
                return True
            elif response.status_code == 503:
                log_test(test_name, "SKIP", 
                        "Service initializing (model loading)")
                return True
            else:
                log_test(test_name, "FAIL", f"Status: {response.status_code}")
                return False
        except Exception as e:
            log_test(test_name, "FAIL", f"Error: {str(e)}")
            return False


async def run_all_tests():
    """Run all service tests"""
    print(f"\n{BLUE}{'='*60}")
    print(f"June Services Integration Tests")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}{RESET}\n")
    
    # Test IDP
    print(f"\n{BLUE}Testing Identity Provider (Keycloak){RESET}")
    print("-" * 60)
    idp_tester = IDPTester()
    await idp_tester.test_connectivity()
    await idp_tester.test_health()
    await idp_tester.test_oidc_discovery()
    await idp_tester.test_jwks()
    await idp_tester.close()
    
    # Test Orchestrator
    print(f"\n{BLUE}Testing Orchestrator Service{RESET}")
    print("-" * 60)
    orch_tester = OrchestratorTester()
    await orch_tester.test_connectivity()
    await orch_tester.test_health()
    await orch_tester.test_info()
    await orch_tester.test_chat_basic()
    await orch_tester.test_tts_status()
    await orch_tester.close()
    
    # Test TTS
    print(f"\n{BLUE}Testing Text-to-Speech Service{RESET}")
    print("-" * 60)
    tts_tester = TTSTester()
    await tts_tester.test_connectivity()
    await tts_tester.test_health()
    await tts_tester.test_voices()
    await tts_tester.test_status()
    await tts_tester.test_synthesis_basic()
    await tts_tester.close()
    
    # Test STT
    print(f"\n{BLUE}Testing Speech-to-Text Service{RESET}")
    print("-" * 60)
    stt_tester = STTTester()
    await stt_tester.test_connectivity()
    await stt_tester.test_health()
    await stt_tester.test_capabilities()
    await stt_tester.test_ready()
    await stt_tester.close()
    
    # Print summary
    print(f"\n{BLUE}{'='*60}")
    print("Test Summary")
    print(f"{'='*60}{RESET}")
    print(f"{GREEN}Passed:{RESET}  {test_results['passed']}")
    print(f"{RED}Failed:{RESET}  {test_results['failed']}")
    print(f"{YELLOW}Skipped:{RESET} {test_results['skipped']}")
    print(f"Total:   {test_results['passed'] + test_results['failed'] + test_results['skipped']}")
    
    # Save detailed results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = f"june_test_results_{timestamp}.json"
    with open(results_file, 'w') as f:
        json.dump(test_results, f, indent=2)
    print(f"\n{BLUE}Detailed results saved to: {results_file}{RESET}")
    
    # Exit code based on results
    if test_results['failed'] > 0:
        print(f"\n{RED}Tests FAILED{RESET}")
        return 1
    elif test_results['passed'] == 0:
        print(f"\n{YELLOW}No tests passed{RESET}")
        return 1
    else:
        print(f"\n{GREEN}All tests PASSED{RESET}")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)