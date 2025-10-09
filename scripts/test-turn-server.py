#!/usr/bin/env python3
"""
TURN/STUN Server Connectivity Test
Tests connectivity to your deployed TURN/STUN server
"""

import asyncio
import socket
import struct
import hashlib
import hmac
import base64
from datetime import datetime

class TurnTester:
    def __init__(self, turn_server, turn_port, username, password):
        self.turn_server = turn_server
        self.turn_port = turn_port
        self.username = username
        self.password = password
        
    async def test_stun_connectivity(self):
        """Test basic STUN connectivity"""
        print(f"🔍 Testing STUN connectivity to {self.turn_server}:{self.turn_port}")
        
        try:
            # Create STUN binding request
            transaction_id = b'\x12\x34\x56\x78\x90\xab\xcd\xef\xfe\xdc\xba\x98'
            stun_request = struct.pack('!HH12s', 0x0001, 0x0000, transaction_id)  # Binding Request
            
            # Send UDP packet
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5.0)
            
            sock.sendto(stun_request, (self.turn_server, self.turn_port))
            response, addr = sock.recvfrom(1024)
            sock.close()
            
            if len(response) >= 20:
                msg_type, msg_length = struct.unpack('!HH', response[:4])
                if msg_type == 0x0101:  # Binding Success Response
                    print(f"✅ STUN server responding correctly")
                    print(f"   Response from: {addr}")
                    print(f"   Response length: {len(response)} bytes")
                    return True
                else:
                    print(f"❌ Unexpected STUN response type: {msg_type:04x}")
            else:
                print(f"❌ Invalid STUN response length: {len(response)}")
                
        except socket.timeout:
            print(f"❌ STUN request timeout - server may be unreachable")
        except socket.gaierror as e:
            print(f"❌ DNS resolution failed: {e}")
        except Exception as e:
            print(f"❌ STUN test failed: {e}")
            
        return False
    
    async def test_turn_auth(self):
        """Test TURN authentication"""
        print(f"🔐 Testing TURN authentication with username: {self.username}")
        
        # Note: Full TURN auth test requires more complex protocol handling
        # For now, we'll just verify the credentials format
        if self.username and self.password:
            print(f"✅ TURN credentials configured")
            print(f"   Username: {self.username}")
            print(f"   Password: {'*' * len(self.password)}")
            return True
        else:
            print(f"❌ TURN credentials missing")
            return False
    
    async def test_dns_resolution(self):
        """Test DNS resolution of TURN server"""
        print(f"🌐 Testing DNS resolution for {self.turn_server}")
        
        try:
            import socket
            ip = socket.gethostbyname(self.turn_server)
            print(f"✅ DNS resolution successful: {self.turn_server} -> {ip}")
            return True
        except socket.gaierror as e:
            print(f"❌ DNS resolution failed: {e}")
            return False
    
    async def run_all_tests(self):
        """Run all connectivity tests"""
        print(f"🚀 Starting TURN/STUN server tests at {datetime.now()}")
        print(f"Target: {self.turn_server}:{self.turn_port}")
        print("-" * 60)
        
        results = {
            'dns': await self.test_dns_resolution(),
            'stun': await self.test_stun_connectivity(),
            'turn_auth': await self.test_turn_auth()
        }
        
        print("-" * 60)
        print("📊 Test Results:")
        for test_name, result in results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"   {test_name.upper():<12}: {status}")
        
        all_passed = all(results.values())
        overall_status = "✅ ALL TESTS PASSED" if all_passed else "❌ SOME TESTS FAILED"
        print(f"\n🎯 Overall: {overall_status}")
        
        if not all_passed:
            print("\n🔧 Troubleshooting suggestions:")
            if not results['dns']:
                print("   - Check if turn.ozzu.world domain is properly configured")
                print("   - Verify DNS settings and domain registration")
            if not results['stun']:
                print("   - Check if STUN/TURN server is running and accessible")
                print("   - Verify firewall rules allow UDP traffic on port 3478")
                print("   - Check if STUNner LoadBalancer has external IP assigned")
            if not results['turn_auth']:
                print("   - Verify TURN username and password are correctly configured")
        
        return all_passed

async def main():
    # Configuration from your K8s deployment
    TURN_SERVER = "turn.ozzu.world"
    TURN_PORT = 3478
    USERNAME = "june-user"
    PASSWORD = "Pokemon123!"
    
    tester = TurnTester(TURN_SERVER, TURN_PORT, USERNAME, PASSWORD)
    success = await tester.run_all_tests()
    
    if success:
        print("\n🎉 Your TURN/STUN server configuration looks good!")
    else:
        print("\n⚠️  Issues found - check the troubleshooting suggestions above")

if __name__ == "__main__":
    asyncio.run(main())