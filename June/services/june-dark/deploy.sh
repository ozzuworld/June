#!/bin/bash

# June Dark OSINT Framework - Docker Compose Deployment Script
# Multi-service architecture deployment

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_blue() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

check_requirements() {
    log_info "Checking system requirements..."
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    # Check Docker Compose
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        log_error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi
    
    # Check system resources
    TOTAL_MEM=$(free -g | awk '/^Mem:/{print $2}')
    if [ "$TOTAL_MEM" -lt 30 ]; then
        log_warn "System has ${TOTAL_MEM}GB RAM. Recommended: 32GB+ for optimal performance."
    else
        log_info "System resources: ${TOTAL_MEM}GB RAM ✓"
    fi
    
    log_info "Requirements check completed."
}

setup_directories() {
    log_info "Setting up data directories..."
    
    # Create required directories
    sudo mkdir -p /data/june-dark/docker-volumes/{es-data,kibana-data,neo4j-data,neo4j-logs,pg-data,redis-data,rabbit-data,minio-data,artifacts,logs}
    
    # Set proper permissions
    sudo chown -R 1000:1000 /data/june-dark/docker-volumes/
    
    log_info "Data directories created and configured."
}

build_services() {
    log_info "Building June Dark OSINT Framework services..."
    
    # Build all services
    docker compose build --no-cache
    
    log_info "All services built successfully!"
}

start_services() {
    log_info "Starting June Dark OSINT Framework..."
    
    # Start infrastructure services first
    log_info "Starting infrastructure services (databases, storage)..."
    docker compose up -d elasticsearch kibana postgres neo4j redis rabbitmq minio
    
    # Wait for infrastructure to be ready
    log_info "Waiting for infrastructure services to be healthy..."
    sleep 60
    
    # Check infrastructure health
    check_infrastructure_health
    
    # Start application services
    log_info "Starting application services..."
    docker compose up -d orchestrator enricher ops-ui collector
    
    # Wait for application services
    log_info "Waiting for application services to start..."
    sleep 45
    
    log_info "June Dark OSINT Framework started successfully!"
    show_access_info
}

stop_services() {
    log_info "Stopping June Dark OSINT Framework..."
    docker compose down
    log_info "All services stopped."
}

restart_services() {
    log_info "Restarting June Dark OSINT Framework..."
    stop_services
    sleep 5
    start_services
}

show_logs() {
    log_info "Showing logs for June Dark OSINT Framework..."
    
    case "${2:-all}" in
        orchestrator|collector|enricher|ops-ui)
            docker compose logs -f $2
            ;;
        infrastructure|infra)
            docker compose logs -f elasticsearch postgres neo4j redis rabbitmq minio
            ;;
        all|*)
            docker compose logs -f
            ;;
    esac
}

check_infrastructure_health() {
    log_info "Checking infrastructure health..."
    
    # Check Elasticsearch
    if curl -s -f http://localhost:9200/_cluster/health > /dev/null 2>&1; then
        log_info "✅ Elasticsearch is healthy"
    else
        log_warn "⚠️  Elasticsearch health check failed"
    fi
    
    # Check Neo4j
    if curl -s -f http://localhost:7474/ > /dev/null 2>&1; then
        log_info "✅ Neo4j is responding"
    else
        log_warn "⚠️  Neo4j health check failed"
    fi
    
    # Check RabbitMQ
    if curl -s -f http://localhost:15672 > /dev/null 2>&1; then
        log_info "✅ RabbitMQ Management is accessible"
    else
        log_warn "⚠️  RabbitMQ health check failed"
    fi
    
    # Check MinIO
    if curl -s -f http://localhost:9000/minio/health/live > /dev/null 2>&1; then
        log_info "✅ MinIO is healthy"
    else
        log_warn "⚠️  MinIO health check failed"
    fi
}

check_status() {
    log_info "Checking June Dark OSINT Framework status..."
    
    echo -e "\n${BLUE}=== Container Status ===${NC}"
    docker compose ps
    
    echo -e "\n${BLUE}=== Service Health Checks ===${NC}"
    
    # Check Orchestrator API
    if curl -s -f http://localhost:8080/health > /dev/null 2>&1; then
        log_info "✅ Orchestrator API is healthy"
        echo "   📖 API Documentation: http://localhost:8080/docs"
    else
        log_warn "⚠️  Orchestrator API health check failed"
    fi
    
    # Check Enricher API  
    if curl -s -f http://localhost:9010/health > /dev/null 2>&1; then
        log_info "✅ Enricher API is healthy"
    else
        log_warn "⚠️  Enricher API health check failed"
    fi
    
    # Check Ops UI
    if curl -s -f http://localhost:8090/health > /dev/null 2>&1; then
        log_info "✅ Operations UI is healthy"
        echo "   📊 Operations Dashboard: http://localhost:8090"
    else
        log_warn "⚠️  Operations UI health check failed"
    fi
    
    # Infrastructure health
    check_infrastructure_health
    
    echo -e "\n${BLUE}=== Resource Usage ===${NC}"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" | head -10
}

show_access_info() {
    echo -e "\n${GREEN}🎉 June Dark OSINT Framework is running!${NC}"
    echo -e "\n${BLUE}=== Access Points ===${NC}"
    echo "📖 Main API Documentation:    http://localhost:8080/docs"
    echo "📊 Operations Dashboard:      http://localhost:8090"
    echo "🔍 Kibana Analytics:          http://localhost:5601"
    echo "🕸️  Neo4j Browser:            http://localhost:7474"
    echo "📨 RabbitMQ Management:       http://localhost:15672"
    echo "💾 MinIO Console:             http://localhost:9001"
    echo "⚙️  Enricher API:             http://localhost:9010/docs"
    
    echo -e "\n${BLUE}=== Default Credentials ===${NC}"
    echo "Neo4j:    neo4j / juneN3o4j2024"
    echo "RabbitMQ: juneadmin / juneR@bbit2024"
    echo "MinIO:    juneadmin / juneM1ni0P@ss2024"
    
    echo -e "\n${BLUE}=== Quick Health Check ===${NC}"
    echo "curl http://localhost:8080/health"
}

clean_system() {
    log_warn "This will remove all containers, images, and data. Are you sure? (y/N)"
    read -r response
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        log_info "Cleaning up June Dark OSINT Framework..."
        docker compose down -v
        docker system prune -af
        sudo rm -rf /data/june-dark/docker-volumes/
        log_info "System cleaned."
    else
        log_info "Clean operation cancelled."
    fi
}

show_help() {
    echo "June Dark OSINT Framework - Docker Compose Deployment Script"
    echo ""
    echo "Usage: $0 [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  setup         Set up data directories and requirements"
    echo "  build         Build all Docker images"
    echo "  start         Start all services"
    echo "  stop          Stop all services"
    echo "  restart       Restart all services"
    echo "  status        Show service status and health"
    echo "  logs [svc]    Show logs (all, orchestrator, collector, enricher, ops-ui, infra)"
    echo "  clean         Clean up all containers and data (DESTRUCTIVE)"
    echo "  help          Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 setup                 # Initial setup"
    echo "  $0 build                 # Build all services"
    echo "  $0 start                 # Start the framework"
    echo "  $0 status                # Check if everything is working"
    echo "  $0 logs orchestrator     # View orchestrator logs"
    echo "  $0 logs infra           # View infrastructure logs"
    echo ""
    echo "Full Deployment:"
    echo "  $0 setup && $0 build && $0 start"
}

# Main script logic
case "${1:-help}" in
    setup)
        check_requirements
        setup_directories
        ;;
    build)
        check_requirements
        build_services
        ;;
    start)
        setup_directories
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        restart_services
        ;;
    logs)
        show_logs "$@"
        ;;
    status)
        check_status
        ;;
    clean)
        clean_system
        ;;
    deploy)
        # Full deployment
        check_requirements
        setup_directories
        build_services
        start_services
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac