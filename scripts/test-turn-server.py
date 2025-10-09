#!/usr/bin/env python3
"""Enhanced TURN/STUN Server Test"""

import socket
import struct

def test_stun_udp(server, port):
    """Test STUN over UDP"""
    print(f"🔍 Testing STUN UDP on {server}:{port}")
    
    try:
        # Create STUN binding request
        transaction_id = b'\x12\x34\x56\x78\x90\xab\xcd\xef\xfe\xdc\xba\x98'
        stun_request = struct.pack('!HH12s', 0x0001, 0x0000, transaction_id)
        
        # Create UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5.0)
        
        print(f"📤 Sending STUN request ({len(stun_request)} bytes)...")
        sock.sendto(stun_request, (server, port))
        
        print(f"⏳ Waiting for response (5s timeout)...")
        response, addr = sock.recvfrom(1024)
        sock.close()
        
        print(f"✅ Received response: {len(response)} bytes from {addr}")
        
        if len(response) >= 20:
            msg_type, msg_length = struct.unpack('!HH', response[:4])
            print(f"   Message type: 0x{msg_type:04x}")
            print(f"   Message length: {msg_length}")
            
            if msg_type == 0x0101:  # Binding Success Response
                print(f"✅ STUN server is working correctly!")
                return True
            else:
                print(f"❌ Unexpected STUN response type: 0x{msg_type:04x}")
        else:
            print(f"❌ Invalid STUN response length: {len(response)}")
            
    except socket.timeout:
        print(f"❌ STUN request timeout")
        print(f"   Possible causes:")
        print(f"   - UDP port 3478 is blocked by firewall")
        print(f"   - Server is not listening on UDP")
        print(f"   - Network connectivity issue")
    except Exception as e:
        print(f"❌ STUN test failed: {e}")
        
    return False

def test_tcp_connectivity(server, port):
    """Test basic TCP connectivity"""
    print(f"\n🔍 Testing TCP connectivity on {server}:{port}")
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((server, port))
        sock.close()
        print(f"✅ TCP connection successful")
        return True
    except Exception as e:
        print(f"❌ TCP connection failed: {e}")
        return False

if __name__ == "__main__":
    SERVER = "turn.ozzu.world"
    PORT = 3478
    
    print(f"🚀 Enhanced TURN/STUN Connectivity Test")
    print(f"=" * 60)
    print(f"Target: {SERVER}:{PORT}")
    print(f"=" * 60)
    
    # Test DNS
    print(f"\n🌐 DNS Resolution:")
    try:
        ip = socket.gethostbyname(SERVER)
        print(f"✅ {SERVER} → {ip}")
    except Exception as e:
        print(f"❌ DNS failed: {e}")
        exit(1)
    
    # Test TCP (should work)
    tcp_ok = test_tcp_connectivity(SERVER, PORT)
    
    # Test UDP STUN (this is what we need to fix)
    udp_ok = test_stun_udp(SERVER, PORT)
    
    print(f"\n" + "=" * 60)
    print(f"📊 Results:")
    print(f"  TCP: {'✅ PASS' if tcp_ok else '❌ FAIL'}")
    print(f"  UDP: {'✅ PASS' if udp_ok else '❌ FAIL'}")
    
    if tcp_ok and not udp_ok:
        print(f"\n⚠️  TCP works but UDP doesn't!")
        print(f"🔧 Troubleshooting steps:")
        print(f"  1. Check firewall: ufw allow 3478/udp")
        print(f"  2. Check listener: ss -ulnp | grep 3478")
        print(f"  3. Test locally: echo test | nc -u -w1 127.0.0.1 3478")
    
    print(f"=" * 60)