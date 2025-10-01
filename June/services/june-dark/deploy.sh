#!/bin/bash

# June Dark OSINT Framework - Complete Deployment Script with Progress Indicators
# Multi-service architecture with reverse proxy and testing

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
DEPLOY_TIMEOUT=300
TEST_TIMEOUT=60
PUBLIC_IP=$(curl -s ifconfig.me || echo "localhost")

# Progress spinner
spin() {
    local -a spinner=('|' '/' '-' '\')
    local i=0
    while :; do
        printf "\r${CYAN}[${spinner[i]}]${NC} $1"
        sleep 0.2
        i=$(((i + 1) % 4))
    done
}

# Stop spinner
stop_spin() {
    kill $! 2>/dev/null || true
    printf "\r${GREEN}[✓]${NC} $1\n"
}

# Progress bar
progress_bar() {
    local duration=$1
    local description=$2
    local progress=0
    local bar_length=30
    
    echo -e "${CYAN}$description${NC}"
    
    while [ $progress -le $duration ]; do
        local filled=$((progress * bar_length / duration))
        local empty=$((bar_length - filled))
        
        printf "\r${GREEN}["
        printf "%*s" $filled | tr ' ' '='
        printf "%*s" $empty | tr ' ' ' '
        printf "] %d%% (%ds)" $((progress * 100 / duration)) $progress
        
        sleep 1
        progress=$((progress + 1))
    done
    echo -e "${NC}"
}

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

log_debug() {
    echo -e "${CYAN}[DEBUG]${NC} $1"
}

log_step() {
    echo -e "\n${BLUE}🔄 STEP: $1${NC}"
}

check_requirements() {
    log_step "Checking System Requirements"
    log_debug "Verifying Docker installation..."
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    log_debug "Docker found: $(docker --version)"
    
    # Check Docker Compose
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        log_error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi
    log_debug "Docker Compose found: $(docker compose version --short 2>/dev/null || docker-compose --version)"
    
    # Check system resources
    TOTAL_MEM=$(free -g | awk '/^Mem:/{print $2}')
    AVAILABLE_MEM=$(free -g | awk '/^Mem:/{print $7}')
    TOTAL_DISK=$(df -h / | awk 'NR==2{print $2}')
    AVAILABLE_DISK=$(df -h / | awk 'NR==2{print $4}')
    
    log_debug "System resources detected:"
    log_debug "  - Total Memory: ${TOTAL_MEM}GB"
    log_debug "  - Available Memory: ${AVAILABLE_MEM}GB"
    log_debug "  - Total Disk: ${TOTAL_DISK}"
    log_debug "  - Available Disk: ${AVAILABLE_DISK}"
    
    if [ "$TOTAL_MEM" -lt 30 ]; then
        log_warn "System has ${TOTAL_MEM}GB RAM. Recommended: 32GB+ for optimal performance."
    else
        log_info "System resources: ${TOTAL_MEM}GB RAM ✓"
    fi
    
    log_info "Requirements check completed."
}

setup_directories() {
    log_step "Setting Up Data Directories"
    
    log_debug "Creating Docker volume directories..."
    spin "Creating directories..." &
    
    # Create required directories
    sudo mkdir -p /data/june-dark/docker-volumes/{es-data,kibana-data,neo4j-data,neo4j-logs,pg-data,redis-data,rabbit-data,minio-data,artifacts,logs}
    
    stop_spin "Docker volume directories created"
    
    log_debug "Setting directory permissions..."
    spin "Setting permissions..." &
    
    # Set proper permissions
    sudo chown -R 1000:1000 /data/june-dark/docker-volumes/
    
    stop_spin "Directory permissions set"
    
    log_debug "Creating nginx configuration directory..."
    # Create nginx config directory
    mkdir -p configs/nginx
    
    log_debug "Verifying directory structure..."
    log_debug "Data directories created:"
    ls -la /data/june-dark/docker-volumes/ | head -5
    
    log_info "Data directories setup completed."
}

build_services() {
    log_step "Building Docker Services"
    
    log_debug "Starting Docker image build process..."
    log_debug "This may take 3-5 minutes depending on your internet connection..."
    
    # Show build progress
    echo -e "${CYAN}Building services... This will take a few minutes.${NC}"
    
    # Start build with progress
    spin "Building Docker images..." &
    
    # Build all services with timeout
    if timeout $DEPLOY_TIMEOUT docker compose build --no-cache > /tmp/build.log 2>&1; then
        stop_spin "Docker images built successfully"
        
        # Show what was built
        log_debug "Built images:"
        docker images | grep june-dark | while read line; do
            log_debug "  - $line"
        done
    else
        stop_spin "Build failed or timed out"
        log_error "Build failed or timed out after ${DEPLOY_TIMEOUT} seconds"
        log_error "Build log (last 20 lines):"
        tail -20 /tmp/build.log
        exit 1
    fi
    
    log_info "All services built successfully!"
}

start_services() {
    log_step "Starting Services in Correct Order"
    
    # Start infrastructure services first
    log_debug "Phase 1: Starting infrastructure services..."
    log_debug "Services: Elasticsearch, Kibana, PostgreSQL, Neo4j, Redis, RabbitMQ, MinIO"
    
    spin "Starting infrastructure services..." &
    docker compose up -d elasticsearch kibana postgres neo4j redis rabbitmq minio
    stop_spin "Infrastructure services started"
    
    # Wait for infrastructure with progress bar
    log_debug "Phase 2: Waiting for infrastructure to be ready..."
    progress_bar 60 "Waiting for databases and storage services to initialize..."
    
    # Check infrastructure health
    wait_for_infrastructure
    
    # Start application services
    log_debug "Phase 3: Starting application services..."
    log_debug "Services: Orchestrator, Operations UI"
    
    spin "Starting application services..." &
    docker compose up -d orchestrator ops-ui
    stop_spin "Application services started"
    
    # Wait for application services
    progress_bar 45 "Waiting for application services to start..."
    
    # Start reverse proxy
    log_debug "Phase 4: Starting reverse proxy..."
    spin "Starting Nginx reverse proxy..." &
    docker compose up -d nginx
    stop_spin "Nginx reverse proxy started"
    
    # Final wait
    progress_bar 15 "Waiting for reverse proxy to be ready..."
    
    log_info "June Dark OSINT Framework started successfully!"
}

wait_for_infrastructure() {
    log_step "Infrastructure Health Checks"
    
    local max_attempts=20
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        log_debug "Infrastructure health check (attempt $attempt/$max_attempts)..."
        
        local healthy=0
        local total=6
        
        # Check each service with debug info
        log_debug "Checking infrastructure services..."
        
        # Check Elasticsearch
        if curl -s -f http://localhost:9200/_cluster/health > /dev/null 2>&1; then
            log_debug "  ✅ Elasticsearch: Healthy"
            ((healthy++))
        else
            log_debug "  ⚠️  Elasticsearch: Not ready"
        fi
        
        # Check PostgreSQL
        if docker compose exec -T postgres pg_isready > /dev/null 2>&1; then
            log_debug "  ✅ PostgreSQL: Healthy"
            ((healthy++))
        else
            log_debug "  ⚠️  PostgreSQL: Not ready"
        fi
        
        # Check Neo4j
        if curl -s -f http://localhost:7474/ > /dev/null 2>&1; then
            log_debug "  ✅ Neo4j: Responding"
            ((healthy++))
        else
            log_debug "  ⚠️  Neo4j: Not ready"
        fi
        
        # Check Redis
        if docker compose exec -T redis redis-cli ping > /dev/null 2>&1; then
            log_debug "  ✅ Redis: Healthy"
            ((healthy++))
        else
            log_debug "  ⚠️  Redis: Not ready"
        fi
        
        # Check RabbitMQ
        if curl -s -f http://localhost:15672 > /dev/null 2>&1; then
            log_debug "  ✅ RabbitMQ: Management accessible"
            ((healthy++))
        else
            log_debug "  ⚠️  RabbitMQ: Not ready"
        fi
        
        # Check MinIO
        if curl -s -f http://localhost:9000/minio/health/live > /dev/null 2>&1; then
            log_debug "  ✅ MinIO: Healthy"
            ((healthy++))
        else
            log_debug "  ⚠️  MinIO: Not ready"
        fi
        
        log_debug "Infrastructure health: $healthy/$total services ready"
        
        if [ $healthy -eq $total ]; then
            log_info "All infrastructure services are healthy!"
            return 0
        fi
        
        log_debug "Waiting 15 seconds before next health check..."
        sleep 15
        ((attempt++))
    done
    
    log_error "Infrastructure services failed to become healthy after $max_attempts attempts"
    log_error "Current container status:"
    docker compose ps
    return 1
}

run_comprehensive_tests() {
    log_step "Running Comprehensive Tests"
    
    local tests_passed=0
    local total_tests=12
    
    log_debug "Running $total_tests automated tests..."
    
    # Test 1: Container Health
    log_debug "Test 1/12: Checking container health..."
    spin "Testing container health..." &
    local unhealthy=$(docker compose ps --format json 2>/dev/null | jq -r '. | select(.Health == "unhealthy" or (.State != "running" and .State != "Up")) | .Name' 2>/dev/null | wc -l)
    if [ "$unhealthy" -eq 0 ]; then
        stop_spin "✅ All containers are healthy"
        ((tests_passed++))
    else
        stop_spin "❌ Some containers are unhealthy"
    fi
    
    # Test 2: Reverse Proxy
    log_debug "Test 2/12: Testing reverse proxy..."
    if curl -s -f http://localhost/status > /dev/null; then
        log_debug "✅ Reverse proxy is working"
        ((tests_passed++))
    else
        log_debug "❌ Reverse proxy failed"
    fi
    
    # Test 3: Main API
    log_debug "Test 3/12: Testing main API..."
    if curl -s -f http://localhost/health > /dev/null; then
        log_debug "✅ Main API is responding"
        ((tests_passed++))
    else
        log_debug "❌ Main API failed"
    fi
    
    # Test 4: API Documentation
    log_debug "Test 4/12: Testing API documentation..."
    if curl -s -f http://localhost/docs > /dev/null; then
        log_debug "✅ API documentation is accessible"
        ((tests_passed++))
    else
        log_debug "❌ API documentation failed"
    fi
    
    # Test 5: Operations Dashboard
    log_debug "Test 5/12: Testing operations dashboard..."
    if curl -s -f http://localhost/dashboard > /dev/null; then
        log_debug "✅ Operations dashboard is accessible"
        ((tests_passed++))
    else
        log_debug "❌ Operations dashboard failed"
    fi
    
    # Test 6: System Info
    log_debug "Test 6/12: Testing system info..."
    if curl -s -f http://localhost/info > /dev/null; then
        log_debug "✅ System info endpoint is working"
        ((tests_passed++))
    else
        log_debug "❌ System info endpoint failed"
    fi
    
    # Test 7: Elasticsearch
    log_debug "Test 7/12: Testing Elasticsearch..."
    if curl -s -f http://localhost:9200/_cluster/health > /dev/null; then
        log_debug "✅ Elasticsearch cluster is healthy"
        ((tests_passed++))
    else
        log_debug "❌ Elasticsearch cluster failed"
    fi
    
    # Test 8: Kibana
    log_debug "Test 8/12: Testing Kibana..."
    if curl -s -f http://localhost/kibana/api/status > /dev/null; then
        log_debug "✅ Kibana is responding"
        ((tests_passed++))
    else
        log_debug "❌ Kibana failed"
    fi
    
    # Test 9: Neo4j
    log_debug "Test 9/12: Testing Neo4j..."
    if curl -s -f http://localhost/neo4j/ > /dev/null; then
        log_debug "✅ Neo4j browser is accessible"
        ((tests_passed++))
    else
        log_debug "❌ Neo4j browser failed"
    fi
    
    # Test 10: RabbitMQ
    log_debug "Test 10/12: Testing RabbitMQ..."
    if curl -s -f http://localhost:15672 > /dev/null; then
        log_debug "✅ RabbitMQ management is accessible"
        ((tests_passed++))
    else
        log_debug "❌ RabbitMQ management failed"
    fi
    
    # Test 11: MinIO
    log_debug "Test 11/12: Testing MinIO..."
    if curl -s -f http://localhost:9000/minio/health/live > /dev/null; then
        log_debug "✅ MinIO storage is healthy"
        ((tests_passed++))
    else
        log_debug "❌ MinIO storage failed"
    fi
    
    # Test 12: OSINT API Endpoints
    log_debug "Test 12/12: Testing OSINT API endpoints..."
    local api_tests=0
    
    if curl -s -f http://localhost/api/v1/crawl/stats > /dev/null; then
        ((api_tests++))
        log_debug "  ✅ Crawl API working"
    fi
    if curl -s -f http://localhost/api/v1/alerts/stats/summary > /dev/null; then
        ((api_tests++))
        log_debug "  ✅ Alerts API working"
    fi
    if curl -s -f http://localhost/api/v1/system/stats > /dev/null; then
        ((api_tests++))
        log_debug "  ✅ System API working"
    fi
    
    if [ $api_tests -eq 3 ]; then
        log_debug "✅ All OSINT API endpoints are working"
        ((tests_passed++))
    else
        log_debug "❌ Some OSINT API endpoints failed ($api_tests/3 working)"
    fi
    
    # Test Results
    echo -e "\n${BLUE}=== TEST RESULTS ===${NC}"
    echo -e "${GREEN}Tests Passed: $tests_passed/$total_tests${NC}"
    
    # Show test progress bar
    local success_percent=$((tests_passed * 100 / total_tests))
    echo -e "${CYAN}Success Rate: $success_percent%${NC}"
    
    if [ $tests_passed -eq $total_tests ]; then
        log_info "🎉 ALL TESTS PASSED! Deployment is successful."
        return 0
    elif [ $tests_passed -ge 9 ]; then
        log_warn "⚠️  Most tests passed ($tests_passed/$total_tests). Deployment is mostly successful."
        return 0
    else
        log_error "❌ Too many tests failed ($tests_passed/$total_tests). Deployment has issues."
        return 1
    fi
}

show_access_info() {
    log_step "Deployment Complete - Access Information"
    
    echo -e "\n${GREEN}🎉 June Dark OSINT Framework is running!${NC}"
    echo -e "\n${BLUE}=== Primary Access Points ===${NC}"
    echo "🌐 Main Interface:            http://${PUBLIC_IP}/"
    echo "📖 API Documentation:        http://${PUBLIC_IP}/docs"
    echo "📊 Operations Dashboard:     http://${PUBLIC_IP}/dashboard"
    echo "🔍 System Health:            http://${PUBLIC_IP}/health"
    echo "ℹ️  System Information:       http://${PUBLIC_IP}/info"
    
    echo -e "\n${BLUE}=== Analytics & Management ===${NC}"
    echo "📈 Kibana Analytics:         http://${PUBLIC_IP}/kibana/"
    echo "🕸️  Neo4j Graph Browser:     http://${PUBLIC_IP}/neo4j/"
    echo "📨 RabbitMQ Management:      http://${PUBLIC_IP}:15672"
    echo "💾 MinIO Console:            http://${PUBLIC_IP}:9001"
    
    echo -e "\n${BLUE}=== Default Credentials ===${NC}"
    echo "Neo4j:    neo4j / juneN3o4j2024"
    echo "RabbitMQ: juneadmin / juneR@bbit2024"
    echo "MinIO:    juneadmin / juneM1ni0P@ss2024"
    
    echo -e "\n${BLUE}=== Quick Tests ===${NC}"
    echo "curl http://${PUBLIC_IP}/health"
    echo "curl http://${PUBLIC_IP}/info"
    echo "curl http://${PUBLIC_IP}/api/v1/system/stats"
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
    sleep 30
    run_comprehensive_tests
}

show_logs() {
    log_info "Showing logs for June Dark OSINT Framework..."
    
    case "${2:-all}" in
        orchestrator|ops-ui|nginx)
            docker compose logs -f $2
            ;;
        infrastructure|infra)
            docker compose logs -f elasticsearch postgres neo4j redis rabbitmq minio kibana
            ;;
        all|*)
            docker compose logs -f
            ;;
    esac
}

check_status() {
    log_info "Checking June Dark OSINT Framework status..."
    
    echo -e "\n${BLUE}=== Container Status ===${NC}"
    docker compose ps
    
    echo -e "\n${BLUE}=== Quick Health Check ===${NC}"
    run_comprehensive_tests
    
    echo -e "\n${BLUE}=== Resource Usage ===${NC}"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" | head -12
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

full_deployment() {
    log_step "Starting Full June Dark OSINT Framework Deployment"
    
    echo -e "${GREEN}🚀 Welcome to June Dark OSINT Framework Automated Deployment${NC}"
    echo -e "${CYAN}This will take approximately 5-10 minutes...${NC}\n"
    
    local start_time=$(date +%s)
    
    check_requirements
    setup_directories
    build_services
    start_services
    
    log_debug "Waiting for all services to stabilize..."
    progress_bar 60 "Final stabilization period..."
    
    run_comprehensive_tests
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local minutes=$((duration / 60))
    local seconds=$((duration % 60))
    
    if [ $? -eq 0 ]; then
        show_access_info
        echo -e "\n${GREEN}✅ Deployment completed successfully in ${minutes}m ${seconds}s!${NC}"
    else
        log_error "❌ Deployment completed with issues after ${minutes}m ${seconds}s. Check logs for details."
        exit 1
    fi
}

show_help() {
    echo "June Dark OSINT Framework - Complete Deployment Script"
    echo ""
    echo "Usage: $0 [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  deploy        Full deployment with testing"
    echo "  setup         Set up data directories and requirements"
    echo "  build         Build all Docker images"
    echo "  start         Start all services"
    echo "  stop          Stop all services"
    echo "  restart       Restart all services with testing"
    echo "  test          Run comprehensive tests"
    echo "  status        Show service status and health"
    echo "  logs [svc]    Show logs (all, orchestrator, ops-ui, nginx, infra)"
    echo "  clean         Clean up all containers and data (DESTRUCTIVE)"
    echo "  help          Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 deploy                # Full automated deployment"
    echo "  $0 test                  # Test current deployment"
    echo "  $0 status                # Check if everything is working"
    echo "  $0 logs nginx            # View nginx logs"
    echo "  $0 restart               # Restart with health checks"
    echo ""
    echo "Full Automated Deployment:"
    echo "  $0 deploy"
}

# Main script logic
case "${1:-help}" in
    deploy)
        full_deployment
        ;;
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
    test)
        run_comprehensive_tests
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
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac
