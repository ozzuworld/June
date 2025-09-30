# Full deployment
./deploy.sh deploy

# Or step by step
./deploy.sh setup    # Set up directories  
./deploy.sh build    # Build services
./deploy.sh start    # Start services
./deploy.sh status   # Check health

# Maintenance
./deploy.sh logs orchestrator    # View logs
./deploy.sh restart             # Restart all services
./deploy.sh stop               # Stop services

echo "🎯 **JUNE DARK OSINT FRAMEWORK - READY TO USE!**"
echo ""
echo "📖 Main API Documentation:    http://$(curl -s ifconfig.me):8080/docs"
echo "📊 Operations Dashboard:      http://$(curl -s ifconfig.me):8090"
echo "🔍 Kibana Analytics:          http://$(curl -s ifconfig.me):5601"
echo "🕸️  Neo4j Graph Database:     http://$(curl -s ifconfig.me):7474"
echo "📨 RabbitMQ Management:       http://$(curl -s ifconfig.me):15672"
echo "💾 MinIO Object Storage:      http://$(curl -s ifconfig.me):9001"
echo ""
echo "🔐 Default Credentials:"
echo "Neo4j:    neo4j / juneN3o4j2024"
echo "RabbitMQ: juneadmin / juneR@bbit2024"
echo "MinIO:    juneadmin / juneM1ni0P@ss2024"

echo ""
echo "🚀 Test your OSINT framework:"
echo "curl http://localhost:8080/api/v1/crawl/stats"
echo "curl http://localhost:8080/api/v1/system/stats"
echo "curl http://localhost:8080/info"


###############################################################
GCP OPEN PORT

# Commands to run if you need to open ports (run these if external access fails)
echo "If external access fails, run these commands:"
echo ""
echo "# Open main API ports"
echo "gcloud compute firewall-rules create june-dark-api --allow tcp:8080 --source-ranges 0.0.0.0/0"
echo "gcloud compute firewall-rules create june-dark-ops --allow tcp:8090 --source-ranges 0.0.0.0/0"
echo ""
echo "# Open additional service ports (optional)"
echo "gcloud compute firewall-rules create june-dark-kibana --allow tcp:5601 --source-ranges 0.0.0.0/0"
echo "gcloud compute firewall-rules create june-dark-neo4j --allow tcp:7474 --source-ranges 0.0.0.0/0"
echo "gcloud compute firewall-rules create june-dark-rabbitmq --allow tcp:15672 --source-ranges 0.0.0.0/0"
echo "gcloud compute firewall-rules create june-dark-minio --allow tcp:9001 --source-ranges 0.0.0.0/0"
