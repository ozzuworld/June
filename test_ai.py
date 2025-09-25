# test_ai.py - Test your Gemini AI configuration
import os
import asyncio
import httpx

async def test_gemini_directly():
    """Test Gemini API directly"""
    try:
        import google.generativeai as genai
        
        api_key = os.getenv("GEMINI_API_KEY") or "YOUR_API_KEY_HERE"
        if api_key == "YOUR_API_KEY_HERE":
            print("❌ Please set GEMINI_API_KEY environment variable")
            return False
            
        print(f"🔧 Configuring Gemini with key: {api_key[:10]}...")
        genai.configure(api_key=api_key)
        
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        print("🤖 Testing Gemini API...")
        response = model.generate_content("Hello! Please respond with a friendly greeting.")
        
        print(f"✅ Gemini Response: {response.text}")
        return True
        
    except ImportError:
        print("❌ google.generativeai not installed. Install with:")
        print("   pip install google-generativeai>=0.3.0")
        return False
    except Exception as e:
        print(f"❌ Gemini API Error: {e}")
        return False

async def test_orchestrator_api():
    """Test your orchestrator API"""
    try:
        # Update this URL to match your deployment
        base_url = "https://api.allsafe.world"  # or http://localhost:8080
        
        async with httpx.AsyncClient(timeout=30) as client:
            # Test health first
            print("🏥 Testing orchestrator health...")
            health = await client.get(f"{base_url}/healthz")
            
            if health.status_code != 200:
                print(f"❌ Health check failed: {health.status_code}")
                return False
                
            print("✅ Orchestrator is healthy")
            
            # Test conversation (you'll need a valid token for this)
            print("💬 Testing conversation endpoint...")
            print("   (This requires authentication - check logs for AI status)")
            
            # You can check the logs to see if AI is working:
            # kubectl logs deployment/june-orchestrator -n june-services
            
    except Exception as e:
        print(f"❌ Orchestrator API Error: {e}")
        return False

async def main():
    print("=== June AI Configuration Test ===\n")
    
    # Test 1: Direct Gemini API
    print("Test 1: Direct Gemini API")
    await test_gemini_directly()
    print()
    
    # Test 2: Orchestrator API  
    print("Test 2: Orchestrator API")
    await test_orchestrator_api()
    print()
    
    print("=== Next Steps ===")
    print("1. If Gemini API works directly but not in the app:")
    print("   - Check container environment variables")
    print("   - Verify Kubernetes secrets")
    print("   - Restart the orchestrator service")
    print()
    print("2. Check orchestrator logs:")
    print("   kubectl logs deployment/june-orchestrator -n june-services")
    print()
    print("3. Look for these log messages:")
    print("   - '✅ Gemini AI initialized successfully'")
    print("   - '🤖 Using Gemini AI for: ...'")
    print("   - '✅ AI response generated: ...'")

if __name__ == "__main__":
    asyncio.run(main())