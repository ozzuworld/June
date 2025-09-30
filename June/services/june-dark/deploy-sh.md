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
