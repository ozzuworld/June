# June/test_integration.py
import asyncio
import httpx

async def test_full_pipeline():
    # Update these URLs based on how you're running the services
    
    # If running via Docker Compose:
    orchestrator_url = "https://api.allsafe.world"  # june-orchestrator service
    
    # If running services individually:
    # orchestrator_url = "http://localhost:8080"  # check the actual port
    
    async with httpx.AsyncClient() as client:
        try:
            # 1. Test orchestrator health
            print("Testing orchestrator health...")
            health = await client.get(f"{orchestrator_url}/healthz")
            print(f"Health check: {health.status_code}")
            
            if health.status_code == 200:
                print("✅ Orchestrator is running")
            else:
                print("❌ Orchestrator health check failed")
                return
                
        except Exception as e:
            print(f"❌ Could not connect to orchestrator: {e}")
            print("Make sure the service is running on the expected port")
            return

        # 2. Test conversation endpoint (you'll need a real token)
        # headers = {"Authorization": "Bearer YOUR_KEYCLOAK_TOKEN_HERE"}
        
        # conversation = await client.post(
        #     f"{orchestrator_url}/v1/conversation",
        #     json={
        #         "text": "Hello, test message",
        #         "language": "en"
        #     },
        #     headers=headers
        # )
        
        # print(f"Conversation test: {conversation.status_code}")

if __name__ == "__main__":
    asyncio.run(test_full_pipeline())