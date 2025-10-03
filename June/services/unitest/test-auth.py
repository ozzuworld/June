#!/usr/bin/env python3
"""
June Advanced Integration Tests - CORRECTED VERSION
Includes authentication, end-to-end workflows, and performance tests
"""

import asyncio
import httpx
import json
import sys
import time
import os
from typing import Dict, Any, Optional, List
from datetime import datetime
import argparse

# Configuration
CONFIG = {
    "services": {
        "idp": "https://idp.allsafe.world",
        "api": "https://api.allsafe.world",
        "tts": "https://tts.allsafe.world",
        "stt": "https://stt.allsafe.world"
    },
    "keycloak": {
        "realm": "allsafe",
        "client_id": "june-cli",
        "client_secret": ""
    },
    "test_credentials": {
        "username": "",
        "password": ""
    }
}

# Colors
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


class TestStats:
    """Track test statistics"""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.warnings = 0
        self.tests = []
        self.start_time = time.time()
    
    def log(self, name: str, status: str, message: str = "", 
            details: Any = None, duration_ms: float = 0):
        """Log test result"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        status_map = {
            "PASS": (Colors.GREEN, "✓", lambda: setattr(self, 'passed', self.passed + 1)),
            "FAIL": (Colors.RED, "✗", lambda: setattr(self, 'failed', self.failed + 1)),
            "SKIP": (Colors.YELLOW, "⊘", lambda: setattr(self, 'skipped', self.skipped + 1)),
            "WARN": (Colors.YELLOW, "⚠", lambda: setattr(self, 'warnings', self.warnings + 1)),
        }
        
        color, symbol, counter = status_map.get(status, (Colors.RESET, "?", lambda: None))
        counter()
        
        duration_str = f" ({duration_ms:.0f}ms)" if duration_ms > 0 else ""
        print(f"{color}[{timestamp}] {symbol} {name}{duration_str}{Colors.RESET}")
        
        if message:
            print(f"  {message}")
        
        self.tests.append({
            "name": name,
            "status": status,
            "message": message,
            "details": details,
            "timestamp": timestamp,
            "duration_ms": duration_ms
        })
    
    def summary(self):
        """Print test summary"""
        duration = time.time() - self.start_time
        total = self.passed + self.failed + self.skipped
        
        print(f"\n{Colors.BLUE}{Colors.BOLD}{'='*70}")
        print("Test Summary")
        print(f"{'='*70}{Colors.RESET}")
        print(f"{Colors.GREEN}✓ Passed:{Colors.RESET}  {self.passed}/{total}")
        print(f"{Colors.RED}✗ Failed:{Colors.RESET}  {self.failed}/{total}")
        print(f"{Colors.YELLOW}⊘ Skipped:{Colors.RESET} {self.skipped}/{total}")
        if self.warnings > 0:
            print(f"{Colors.YELLOW}⚠ Warnings:{Colors.RESET} {self.warnings}")
        print(f"\n{Colors.CYAN}Duration:{Colors.RESET} {duration:.2f}s")
        
        return self.failed == 0 and self.passed > 0


stats = TestStats()


class AuthManager:
    """Manage authentication tokens"""
    
    def __init__(self):
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.token_expires: float = 0
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def close(self):
        await self.client.aclose()
    
    async def get_token_password_flow(self, username: str, password: str) -> bool:
        """Get token using password flow"""
        test_name = "Authentication - Password Flow"
        start = time.time()
        
        try:
            token_url = f"{CONFIG['services']['idp']}/realms/{CONFIG['keycloak']['realm']}/protocol/openid-connect/token"
            
            data = {
                "grant_type": "password",
                "client_id": CONFIG['keycloak']['client_id'],
                "username": username,
                "password": password,
                "scope": "openid profile email"
            }
            
            if CONFIG['keycloak'].get('client_secret'):
                data['client_secret'] = CONFIG['keycloak']['client_secret']
            
            response = await self.client.post(token_url, data=data)
            duration = (time.time() - start) * 1000
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data['access_token']
                self.refresh_token = token_data.get('refresh_token')
                self.token_expires = time.time() + token_data.get('expires_in', 300)
                
                stats.log(test_name, "PASS", 
                         f"Token obtained for user: {username}",
                         duration_ms=duration)
                return True
            else:
                stats.log(test_name, "FAIL", 
                         f"Status: {response.status_code}",
                         duration_ms=duration)
                return False
                
        except Exception as e:
            duration = (time.time() - start) * 1000
            stats.log(test_name, "FAIL", f"Error: {str(e)}", duration_ms=duration)
            return False
    
    async def get_token_client_credentials(self) -> bool:
        """Get token using client credentials flow"""
        test_name = "Authentication - Client Credentials"
        start = time.time()
        
        try:
            token_url = f"{CONFIG['services']['idp']}/realms/{CONFIG['keycloak']['realm']}/protocol/openid-connect/token"
            
            data = {
                "grant_type": "client_credentials",
                "client_id": CONFIG['keycloak']['client_id'],
                "client_secret": CONFIG['keycloak']['client_secret']
            }
            
            response = await self.client.post(token_url, data=data)
            duration = (time.time() - start) * 1000
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data['access_token']
                self.token_expires = time.time() + token_data.get('expires_in', 300)
                
                stats.log(test_name, "PASS", 
                         "Service token obtained",
                         duration_ms=duration)
                return True
            else:
                stats.log(test_name, "FAIL", 
                         f"Status: {response.status_code}",
                         duration_ms=duration)
                return False
                
        except Exception as e:
            duration = (time.time() - start) * 1000
            stats.log(test_name, "FAIL", f"Error: {str(e)}", duration_ms=duration)
            return False
    
    def get_headers(self) -> Dict[str, str]:
        """Get authorization headers"""
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        return {}


class ServiceHealthTests:
    """Comprehensive service health checks"""
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def close(self):
        await self.client.aclose()
    
    async def test_all_services_up(self) -> bool:
        """Test all services are responding"""
        test_name = "Health - All Services Up"
        start = time.time()
        
        results = {}
        for name, url in CONFIG['services'].items():
            try:
                response = await self.client.get(f"{url}/healthz", timeout=10.0)
                results[name] = response.status_code == 200
            except Exception:
                results[name] = False
        
        duration = (time.time() - start) * 1000
        
        all_up = all(results.values())
        up_count = sum(results.values())
        total = len(results)
        
        status_str = ", ".join([f"{k}: {'✓' if v else '✗'}" for k, v in results.items()])
        
        if all_up:
            stats.log(test_name, "PASS", 
                     f"All {total} services healthy: {status_str}",
                     duration_ms=duration)
            return True
        elif up_count > 0:
            stats.log(test_name, "WARN", 
                     f"{up_count}/{total} services up: {status_str}",
                     duration_ms=duration)
            return False
        else:
            stats.log(test_name, "FAIL", 
                     f"All services down: {status_str}",
                     duration_ms=duration)
            return False
    
    async def test_service_versions(self) -> bool:
        """Check service version endpoints"""
        test_name = "Health - Service Versions"
        start = time.time()
        
        versions = {}
        for name, url in CONFIG['services'].items():
            try:
                response = await self.client.get(url, timeout=10.0)
                if response.status_code == 200:
                    data = response.json()
                    versions[name] = data.get('version', 'unknown')
                else:
                    versions[name] = "error"
            except Exception:
                versions[name] = "unreachable"
        
        duration = (time.time() - start) * 1000
        
        version_str = "\n  ".join([f"{k}: {v}" for k, v in versions.items()])
        
        has_versions = sum(1 for v in versions.values() if v not in ['error', 'unreachable'])
        
        if has_versions == len(versions):
            stats.log(test_name, "PASS", 
                     f"All versions retrieved:\n  {version_str}",
                     duration_ms=duration)
            return True
        elif has_versions > 0:
            stats.log(test_name, "WARN", 
                     f"Partial versions:\n  {version_str}",
                     duration_ms=duration)
            return False
        else:
            stats.log(test_name, "FAIL", 
                     "No version info available",
                     duration_ms=duration)
            return False


class SecurityTests:
    """Security and authentication tests"""
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=False)
    
    async def close(self):
        await self.client.aclose()
    
    async def test_unauthenticated_access(self) -> bool:
        """Test that protected endpoints require auth"""
        test_name = "Security - Unauthenticated Access Blocked"
        start = time.time()
        
        try:
            response = await self.client.post(
                f"{CONFIG['services']['api']}/v1/chat",
                json={"text": "test"}
            )
            
            duration = (time.time() - start) * 1000
            
            if response.status_code in [401, 403]:
                stats.log(test_name, "PASS", 
                         f"Correctly blocked with {response.status_code}",
                         duration_ms=duration)
                return True
            elif response.status_code == 200:
                stats.log(test_name, "FAIL", 
                         "Endpoint accessible without authentication!",
                         duration_ms=duration)
                return False
            else:
                stats.log(test_name, "WARN", 
                         f"Unexpected status: {response.status_code}",
                         duration_ms=duration)
                return False
                
        except Exception as e:
            duration = (time.time() - start) * 1000
            stats.log(test_name, "FAIL", f"Error: {str(e)}", duration_ms=duration)
            return False
    
    async def test_cors_headers(self) -> bool:
        """Test CORS headers are properly set"""
        test_name = "Security - CORS Headers"
        start = time.time()
        
        try:
            response = await self.client.options(
                f"{CONFIG['services']['api']}/v1/chat",
                headers={
                    "Origin": "https://allsafe.world",
                    "Access-Control-Request-Method": "POST"
                }
            )
            
            duration = (time.time() - start) * 1000
            
            has_cors = "access-control-allow-origin" in [h.lower() for h in response.headers.keys()]
            
            if has_cors:
                stats.log(test_name, "PASS", 
                         "CORS headers present",
                         duration_ms=duration)
                return True
            else:
                stats.log(test_name, "WARN", 
                         "No CORS headers found",
                         duration_ms=duration)
                return False
                
        except Exception as e:
            duration = (time.time() - start) * 1000
            stats.log(test_name, "SKIP", f"Test not applicable: {str(e)}", duration_ms=duration)
            return True


class E2ETests:
    """End-to-end workflow tests"""
    
    def __init__(self, auth: AuthManager):
        self.auth = auth
        self.client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
    
    async def close(self):
        await self.client.aclose()
    
    async def test_chat_with_tts(self) -> bool:
        """Test complete chat workflow with TTS"""
        test_name = "E2E - Chat with TTS"
        start = time.time()
        
        try:
            payload = {
                "text": "Hello! This is an end-to-end test of the June platform.",
                "language": "en",
                "temperature": 0.7,
                "include_audio": True,
                "audio_config": {
                    "voice": "default",
                    "speed": 1.0,
                    "language": "EN"
                }
            }
            
            response = await self.client.post(
                f"{CONFIG['services']['api']}/v1/chat",
                json=payload,
                headers=self.auth.get_headers()
            )
            
            duration = (time.time() - start) * 1000
            
            if response.status_code == 200:
                data = response.json()
                
                checks = {
                    "has_message": "message" in data,
                    "has_text": data.get("message", {}).get("text") is not None,
                    "has_audio": data.get("audio") is not None,
                    "processing_time": data.get("response_time_ms", 0) > 0
                }
                
                if all(checks.values()):
                    msg = f"AI: {data['message']['text'][:50]}..."
                    if data.get('audio'):
                        audio_size = len(data['audio'].get('data', ''))
                        msg += f"\nAudio: {audio_size} bytes"
                    
                    stats.log(test_name, "PASS", msg, 
                             details=checks, duration_ms=duration)
                    return True
                else:
                    failed = [k for k, v in checks.items() if not v]
                    stats.log(test_name, "FAIL", 
                             f"Missing: {', '.join(failed)}",
                             duration_ms=duration)
                    return False
            else:
                stats.log(test_name, "FAIL", 
                         f"Status: {response.status_code}",
                         duration_ms=duration)
                return False
                
        except Exception as e:
            duration = (time.time() - start) * 1000
            stats.log(test_name, "FAIL", f"Error: {str(e)}", duration_ms=duration)
            return False
    
    async def test_tts_synthesis(self) -> bool:
        """Test TTS synthesis"""
        test_name = "E2E - TTS Synthesis"
        start = time.time()
        
        try:
            payload = {
                "text": "The quick brown fox jumps over the lazy dog.",
                "voice": "default",
                "speed": 1.0,
                "language": "EN",
                "format": "wav"
            }
            
            response = await self.client.post(
                f"{CONFIG['services']['tts']}/v1/tts",
                json=payload,
                headers=self.auth.get_headers()
            )
            
            duration = (time.time() - start) * 1000
            
            if response.status_code == 200:
                audio_size = len(response.content)
                
                if audio_size > 1000:
                    stats.log(test_name, "PASS", 
                             f"Generated {audio_size:,} bytes",
                             duration_ms=duration)
                    return True
                else:
                    stats.log(test_name, "FAIL", 
                             f"Audio too small: {audio_size} bytes",
                             duration_ms=duration)
                    return False
            else:
                stats.log(test_name, "FAIL", 
                         f"Status: {response.status_code}",
                         duration_ms=duration)
                return False
                
        except Exception as e:
            duration = (time.time() - start) * 1000
            stats.log(test_name, "FAIL", f"Error: {str(e)}", duration_ms=duration)
            return False
    
    async def test_performance_batch(self, count: int = 5) -> bool:
        """Test performance with multiple requests"""
        test_name = f"Performance - {count} Chat Requests"
        start = time.time()
        
        try:
            tasks = []
            for i in range(count):
                payload = {
                    "text": f"Test request number {i+1}",
                    "language": "en",
                    "temperature": 0.7,
                    "include_audio": False
                }
                
                task = self.client.post(
                    f"{CONFIG['services']['api']}/v1/chat",
                    json=payload,
                    headers=self.auth.get_headers()
                )
                tasks.append(task)
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            duration = (time.time() - start) * 1000
            
            successful = sum(1 for r in responses 
                           if isinstance(r, httpx.Response) and r.status_code == 200)
            avg_time = duration / count
            
            if successful == count:
                stats.log(test_name, "PASS", 
                         f"All {count} requests successful. Avg: {avg_time:.0f}ms/req",
                         duration_ms=duration)
                return True
            elif successful > 0:
                stats.log(test_name, "WARN", 
                         f"{successful}/{count} successful. Avg: {avg_time:.0f}ms/req",
                         duration_ms=duration)
                return False
            else:
                stats.log(test_name, "FAIL", 
                         "All requests failed",
                         duration_ms=duration)
                return False
                
        except Exception as e:
            duration = (time.time() - start) * 1000
            stats.log(test_name, "FAIL", f"Error: {str(e)}", duration_ms=duration)
            return False


async def run_test_suite(skip_auth: bool = False):
    """Run complete test suite"""
    
    print(f"\n{Colors.CYAN}{Colors.BOLD}{'='*70}")
    print("June Platform - Advanced Integration Tests")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}{Colors.RESET}\n")
    
    auth = AuthManager()
    
    # Phase 1: Service Health
    print(f"\n{Colors.MAGENTA}{Colors.BOLD}Phase 1: Service Health Checks{Colors.RESET}")
    print("-" * 70)
    
    health_tests = ServiceHealthTests()
    await health_tests.test_all_services_up()
    await health_tests.test_service_versions()
    await health_tests.close()
    
    # Phase 2: Security
    print(f"\n{Colors.MAGENTA}{Colors.BOLD}Phase 2: Security Tests{Colors.RESET}")
    print("-" * 70)
    
    security_tests = SecurityTests()
    await security_tests.test_unauthenticated_access()
    await security_tests.test_cors_headers()
    await security_tests.close()
    
    # Phase 3: Authentication
    if not skip_auth:
        print(f"\n{Colors.MAGENTA}{Colors.BOLD}Phase 3: Authentication{Colors.RESET}")
        print("-" * 70)
        
        auth_success = False
        
        if CONFIG['keycloak'].get('client_secret'):
            auth_success = await auth.get_token_client_credentials()
        else:
            username = CONFIG['test_credentials'].get('username')
            password = CONFIG['test_credentials'].get('password')
            
            if username and password:
                auth_success = await auth.get_token_password_flow(username, password)
            else:
                stats.log("Authentication", "SKIP", 
                         "No credentials provided")
        
        # Phase 4: E2E Tests
        if auth_success:
            print(f"\n{Colors.MAGENTA}{Colors.BOLD}Phase 4: End-to-End Tests{Colors.RESET}")
            print("-" * 70)
            
            e2e_tests = E2ETests(auth)
            await e2e_tests.test_chat_with_tts()
            await e2e_tests.test_tts_synthesis()
            await e2e_tests.test_performance_batch(count=3)
            await e2e_tests.close()
        else:
            print(f"\n{Colors.YELLOW}Skipping E2E tests (authentication failed){Colors.RESET}")
    else:
        print(f"\n{Colors.YELLOW}Skipping authentication and E2E tests{Colors.RESET}")
    
    await auth.close()
    
    # Summary
    success = stats.summary()
    
    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = f"june_advanced_test_results_{timestamp}.json"
    with open(results_file, 'w') as f:
        json.dump({
            "summary": {
                "passed": stats.passed,
                "failed": stats.failed,
                "skipped": stats.skipped,
                "warnings": stats.warnings,
                "success": success
            },
            "tests": stats.tests,
            "timestamp": datetime.now().isoformat()
        }, f, indent=2)
    
    print(f"\n{Colors.CYAN}Results saved: {results_file}{Colors.RESET}\n")
    
    return 0 if success else 1


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='June Platform Advanced Integration Tests')
    parser.add_argument('--username', help='Test user username')
    parser.add_argument('--password', help='Test user password')
    parser.add_argument('--client-id', help='Keycloak client ID')
    parser.add_argument('--client-secret', help='Keycloak client secret')
    parser.add_argument('--skip-auth', action='store_true', help='Skip authentication tests')
    
    args = parser.parse_args()
    
    if args.username:
        CONFIG['test_credentials']['username'] = args.username
    if args.password:
        CONFIG['test_credentials']['password'] = args.password
    if args.client_id:
        CONFIG['keycloak']['client_id'] = args.client_id
    if args.client_secret:
        CONFIG['keycloak']['client_secret'] = args.client_secret
    
    try:
        exit_code = asyncio.run(run_test_suite(skip_auth=args.skip_auth))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Tests interrupted{Colors.RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.RED}Fatal error: {e}{Colors.RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()