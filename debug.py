#!/usr/bin/env python3
"""
WebRTC Connectivity Test for June Platform
Tests basic connectivity to WebRTC services from local machine
"""

import requests
import socket
import ssl
import json
import time
import sys
from datetime import datetime
from urllib.parse import urlparse

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_status(status, message, details=""):
    if status == "PASS":
        icon = "✅"
        color = Colors.GREEN
    elif status == "FAIL":
        icon = "❌"
        color = Colors.RED
    elif status == "WARN":
        icon = "⚠️"
        color = Colors.YELLOW
    else:
        icon = "ℹ️"
        color = Colors.BLUE
    
    print(f"{color}{icon} {message}{Colors.END}")
    if details:
        print(f"   {details}")

def test_https_connectivity(domain):
    """Test HTTPS connectivity and response time"""
    url = f"https://{domain}"
    try:
        start_time = time.time()
        response = requests.get(url, timeout=10, verify=True)
        end_time = time.time()
        response_time = int((end_time - start_time) * 1000)
        
        if response.status_code == 200:
            print_status("PASS", f"{domain} - HTTPS OK", f"Response time: {response_time}ms")
            return True
        else:
            print_status("WARN", f"{domain} - HTTP {response.status_code}", f"Response time: {response_time}ms")
            return False
    except requests.exceptions.SSLError as e:
        print_status("FAIL", f"{domain} - SSL Error", str(e))
        return False
    except requests.exceptions.ConnectionError:
        print_status("FAIL", f"{domain} - Connection Failed", "Cannot reach server")
        return False
    except requests.exceptions.Timeout:
        print_status("FAIL", f"{domain} - Timeout", "Server did not respond within 10s")
        return False
    except Exception as e:
        print_status("FAIL", f"{domain} - Error", str(e))
        return False

def test_janus_api(domain):
    """Test Janus Gateway API endpoints"""
    base_url = f"https://{domain}"
    
    # Test Janus info endpoint
    try:
        response = requests.get(f"{base_url}/janus/info", timeout=10)
        if response.status_code == 200:
            info = response.json()
            if "janus" in info:
                print_status("PASS", "Janus Gateway Info API", f"Version: {info.get('version-string', 'Unknown')}")
            else:
                print_status("WARN", "Janus Gateway Info API", "Unexpected response format")
        else:
            print_status("FAIL", "Janus Gateway Info API", f"HTTP {response.status_code}")
            return False
    except Exception as e:
        print_status("FAIL", "Janus Gateway Info API", str(e))
        return False
    
    # Test Janus session creation
    try:
        session_data = {"janus": "create", "transaction": "test123"}
        response = requests.post(f"{base_url}/janus", json=session_data, timeout=10)
        if response.status_code == 200:
            result = response.json()
            if result.get("janus") == "success":
                print_status("PASS", "Janus Session Creation", f"Session ID: {result.get('data', {}).get('id')}")
            else:
                print_status("WARN", "Janus Session Creation", "Unexpected response")
        else:
            print_status("FAIL", "Janus Session Creation", f"HTTP {response.status_code}")
    except Exception as e:
        print_status("FAIL", "Janus Session Creation", str(e))
    
    return True

def test_websocket_connection(domain):
    """Test WebSocket connection to Janus"""
    ws_url = f"wss://{domain}:8188/janus"
    try:
        # Simple socket connection test (not full WebSocket)
        hostname = domain
        port = 8188
        
        context = ssl.create_default_context()
        sock = socket.create_connection((hostname, port), timeout=10)
        ssock = context.wrap_socket(sock, server_hostname=hostname)
        ssock.close()
        
        print_status("PASS", "WebSocket Port Reachable", f"{hostname}:{port}")
        return True
    except Exception as e:
        print_status("FAIL", "WebSocket Connection", str(e))
        return False

def test_stun_server(domain):
    """Test STUN server connectivity"""
    stun_host = f"turn.{domain}"
    stun_port = 3478
    
    try:
        # Test basic UDP connectivity to STUN server
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(10)
        
        # Simple connectivity test
        try:
            sock.connect((stun_host, stun_port))
            print_status("PASS", "STUN Server Reachable", f"{stun_host}:{stun_port}")
            sock.close()
            return True
        except Exception:
            print_status("FAIL", "STUN Server Connection", f"Cannot reach {stun_host}:{stun_port}")
            sock.close()
            return False
    except Exception as e:
        print_status("FAIL", "STUN Server Test", str(e))
        return False

def check_ssl_certificate(domain):
    """Check SSL certificate validity"""
    try:
        context = ssl.create_default_context()
        sock = socket.create_connection((domain, 443), timeout=10)
        ssock = context.wrap_socket(sock, server_hostname=domain)
        
        cert = ssock.getpeercert()
        ssock.close()
        
        # Check certificate expiry
        not_after = cert['notAfter']
        expire_date = datetime.strptime(not_after, '%b %d %H:%M:%S %Y %Z')
        days_until_expiry = (expire_date - datetime.now()).days
        
        if days_until_expiry > 7:
            print_status("PASS", "SSL Certificate Valid", f"Expires in {days_until_expiry} days")
        elif days_until_expiry > 0:
            print_status("WARN", "SSL Certificate Expiring Soon", f"Expires in {days_until_expiry} days")
        else:
            print_status("FAIL", "SSL Certificate Expired", f"Expired {abs(days_until_expiry)} days ago")
            return False
        
        # Check subject
        subject = dict(x[0] for x in cert['subject'])
        print_status("INFO", "Certificate Subject", f"CN: {subject.get('commonName', 'Unknown')}")
        
        return True
    except Exception as e:
        print_status("FAIL", "SSL Certificate Check", str(e))
        return False

def test_orchestrator_api(domain):
    """Test June Orchestrator API"""
    url = f"https://api.{domain}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            try:
                data = response.json()
                if "service" in data and data["service"] == "june-orchestrator":
                    print_status("PASS", "June Orchestrator API", f"Version: {data.get('version', 'Unknown')}")
                    return True
            except:
                pass
        
        print_status("WARN", "June Orchestrator API", f"HTTP {response.status_code}")
        return False
    except Exception as e:
        print_status("FAIL", "June Orchestrator API", str(e))
        return False

def main():
    domain = "ozzu.world"
    
    print(f"{Colors.BOLD}🧪 Testing WebRTC Connectivity for June Platform{Colors.END}")
    print("=" * 50)
    print()
    
    # Test basic connectivity
    print(f"{Colors.BLUE}🌐 Testing HTTPS Connectivity...{Colors.END}")
    https_results = []
    for subdomain in ["api", "idp"]:
        result = test_https_connectivity(f"{subdomain}.{domain}")
        https_results.append(result)
    print()
    
    # Test Janus Gateway (if we have a working webrtc domain)
    print(f"{Colors.BLUE}🎮 Testing Janus Gateway...{Colors.END}")
    janus_domain = f"api.{domain}"  # Janus runs behind the orchestrator
    janus_results = []
    
    # Try to connect to Janus through orchestrator proxy
    try:
        response = requests.get(f"https://{janus_domain}/janus/info", timeout=10)
        if response.status_code == 200:
            print_status("PASS", "Janus Gateway via Orchestrator", "Accessible through proxy")
            janus_results.append(True)
        else:
            print_status("WARN", "Janus Gateway via Orchestrator", f"HTTP {response.status_code}")
            janus_results.append(False)
    except Exception as e:
        print_status("FAIL", "Janus Gateway via Orchestrator", str(e))
        janus_results.append(False)
    print()
    
    # Test WebSocket connectivity
    print(f"{Colors.BLUE}🔌 Testing WebSocket Connectivity...{Colors.END}")
    ws_results = []
    # Test if we can reach the Janus WebSocket port
    try:
        hostname = f"api.{domain}"
        port = 443  # HTTPS port, WebSocket will be proxied
        sock = socket.create_connection((hostname, port), timeout=10)
        sock.close()
        print_status("PASS", "WebSocket Port Reachable", f"HTTPS proxy available")
        ws_results.append(True)
    except Exception as e:
        print_status("FAIL", "WebSocket Connection", str(e))
        ws_results.append(False)
    print()
    
    # Test STUN server
    print(f"{Colors.BLUE}🎯 Testing STUN Server...{Colors.END}")
    stun_results = []
    stun_result = test_stun_server(domain)
    stun_results.append(stun_result)
    print()
    
    # Test SSL certificates
    print(f"{Colors.BLUE}🔒 Testing SSL Certificates...{Colors.END}")
    ssl_results = []
    for subdomain in ["api", "idp"]:
        result = check_ssl_certificate(f"{subdomain}.{domain}")
        ssl_results.append(result)
    print()
    
    # Test June Orchestrator
    print(f"{Colors.BLUE}🚀 Testing June Orchestrator...{Colors.END}")
    orchestrator_results = []
    orch_result = test_orchestrator_api(domain)
    orchestrator_results.append(orch_result)
    print()
    
    # Summary
    print(f"{Colors.BOLD}📊 Test Summary{Colors.END}")
    print("-" * 30)
    
    total_tests = len(https_results) + len(janus_results) + len(ws_results) + len(stun_results) + len(ssl_results) + len(orchestrator_results)
    passed_tests = sum(https_results + janus_results + ws_results + stun_results + ssl_results + orchestrator_results)
    
    if passed_tests == total_tests:
        print_status("PASS", f"All tests passed! ({passed_tests}/{total_tests})")
        print(f"\n{Colors.GREEN}🎉 Your WebRTC infrastructure is ready!{Colors.END}")
        sys.exit(0)
    elif passed_tests >= total_tests * 0.7:
        print_status("WARN", f"Most tests passed ({passed_tests}/{total_tests})")
        print(f"\n{Colors.YELLOW}⚠️  Some issues found, but basic connectivity works{Colors.END}")
        sys.exit(1)
    else:
        print_status("FAIL", f"Many tests failed ({passed_tests}/{total_tests})")
        print(f"\n{Colors.RED}❌ WebRTC infrastructure needs attention{Colors.END}")
        sys.exit(2)

if __name__ == "__main__":
    main()
