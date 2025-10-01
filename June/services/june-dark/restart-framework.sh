#!/bin/bash
echo "🚀 Restarting June Dark OSINT Framework..."
docker compose restart orchestrator ops-ui nginx
sleep 30
echo "✅ Framework restarted!"
echo "📖 Access: http://34.41.165.172/docs"
