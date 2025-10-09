#!/usr/bin/env python3
"""
WebRTC Readiness Test
Verifies that the orchestrator is ready to accept WebRTC connections
"""
import asyncio
import json
from websockets import connect

WS_URL = "ws://0.0.0.0:8080/ws"

async def test_webrtc_readiness():
    """Comprehensive WebRTC readiness check"""
    
    print("\n" + "="*70)
    print("🔍 WebRTC Readiness Check")
    print("="*70 + "\n")
    
    checks = {
        "websocket_connection": False,
        "ice_servers_configured": False,
        "webrtc_signaling": False,
        "can_create_peer_connection": False,
        "audio_processor_ready": False
    }
    
    try:
        async with connect(WS_URL) as ws:
            # Check 1: WebSocket Connection
            print("✅ Check 1: WebSocket connection established")
            checks["websocket_connection"] = True
            
            # Get connection message
            message = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(message)
            
            # Check 2: ICE Servers
            if data.get("ice_servers") and len(data["ice_servers"]) > 0:
                print(f"✅ Check 2: ICE servers configured ({len(data['ice_servers'])} servers)")
                for ice in data["ice_servers"]:
                    print(f"   - {ice['urls']}")
                checks["ice_servers_configured"] = True
            else:
                print("❌ Check 2: No ICE servers configured")
            
            # Check 3: WebRTC Enabled
            if data.get("webrtc_enabled"):
                print("✅ Check 3: WebRTC is enabled")
            else:
                print("❌ Check 3: WebRTC is disabled")
            
            # Check 4: Signaling Test (Send mock offer)
            print("\n📡 Testing WebRTC signaling...")
            
            # Simple valid SDP offer
            mock_sdp = """v=0
o=- 4611731400430051336 2 IN IP4 127.0.0.1
s=-
t=0 0
a=group:BUNDLE 0
a=extmap-allow-mixed
a=msid-semantic: WMS
m=audio 9 UDP/TLS/RTP/SAVPF 111
c=IN IP4 0.0.0.0
a=rtcp:9 IN IP4 0.0.0.0
a=ice-ufrag:test123
a=ice-pwd:test123456789012345678901
a=ice-options:trickle
a=fingerprint:sha-256 AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99
a=setup:actpass
a=mid:0
a=sendrecv
a=rtcp-mux
a=rtpmap:111 opus/48000/2
a=fmtp:111 minptime=10;useinbandfec=1
"""
            
            await ws.send(json.dumps({
                "type": "webrtc_offer",
                "sdp": mock_sdp
            }))
            
            # Wait for answer
            response = await asyncio.wait_for(ws.recv(), timeout=10.0)
            response_data = json.loads(response)
            
            if response_data.get("type") == "webrtc_answer":
                print("✅ Check 4: Received WebRTC answer")
                print(f"   SDP length: {len(response_data['sdp'])} bytes")
                checks["webrtc_signaling"] = True
                checks["can_create_peer_connection"] = True
                
                # Verify SDP format
                if "v=0" in response_data["sdp"]:
                    print("✅ Check 5: SDP format is valid")
                
            else:
                print(f"❌ Check 4: Unexpected response: {response_data.get('type')}")
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    # Final Assessment
    print("\n" + "="*70)
    print("📊 Readiness Summary")
    print("="*70)
    
    for check, passed in checks.items():
        status = "✅" if passed else "❌"
        print(f"{status} {check.replace('_', ' ').title()}")
    
    all_passed = all(checks.values())
    
    print("\n" + "="*70)
    if all_passed:
        print("🎉 WebRTC is READY to receive connections!")
        print("="*70)
        print("\n✅ You can now:")
        print("   1. Connect a WebRTC client (browser or mobile)")
        print("   2. Send audio via WebRTC peer connection")
        print("   3. Receive audio transcriptions")
        print("   4. Get AI responses with TTS audio")
        print("\n📋 Next Steps:")
        print("   - Create a browser-based test client")
        print("   - Or integrate with your React Native app")
        print("   - Test with real audio capture")
        return 0
    else:
        print("⚠️  WebRTC has some issues")
        print("="*70)
        failed = [k for k, v in checks.items() if not v]
        print("\n❌ Failed checks:")
        for check in failed:
            print(f"   - {check.replace('_', ' ').title()}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(test_webrtc_readiness())
    exit(exit_code)