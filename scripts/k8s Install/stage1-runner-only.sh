#!/bin/bash
# Unified GitHub Actions Runner Setup Script
# Location: June/scripts/k8s Install/setup-github-runner.sh
# Handles: Fresh install, Fix permissions, Complete reinstall

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Print colored messages
print_status() {
    local status=$1
    local message=$2
    case $status in
        "ok") echo -e "${GREEN}✅ $message${NC}" ;;
        "warn") echo -e "${YELLOW}⚠️  $message${NC}" ;;
        "error") echo -e "${RED}❌ $message${NC}" ;;
        "info") echo -e "${BLUE}ℹ️  $message${NC}" ;;
        "step") echo -e "${CYAN}🔧 $message${NC}" ;;
    esac
}

# Alias for print_step (same as print_status with "step")
print_step() {
    print_status "step" "$1"
}

print_header() {
    echo ""
    echo -e "${CYAN}================================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}================================================${NC}"
    echo ""
}

# Function to check if runner exists and get its status
check_runner_status() {
    local runner_dir="$1"
    
    if [ ! -d "$runner_dir" ]; then
        return 1  # Runner doesn't exist
    fi
    
    if [ ! -f "$runner_dir/.runner" ]; then
        return 2  # Directory exists but not configured
    fi
    
    # Check if service exists
    if systemctl list-unit-files | grep -q "actions.runner"; then
        if systemctl is-active --quiet actions.runner.*; then
            return 0  # Running
        else
            return 3  # Configured but not running
        fi
    else
        return 4  # Configured but no service
    fi
}

# Function to diagnose runner issues
diagnose_runner() {
    local runner_dir="$1"
    local issues=()
    
    print_step "🔍 Diagnosing runner issues..."
    
    # Check _diag directory permissions
    if [ -d "$runner_dir/_diag" ]; then
        local perm=$(stat -c %a "$runner_dir/_diag")
        if [ "$perm" != "777" ]; then
            issues+=("_diag directory has incorrect permissions ($perm, should be 777)")
        fi
    else
        issues+=("_diag directory missing")
    fi
    
    # Check .env file
    if [ ! -f "$runner_dir/.env" ]; then
        issues+=(".env file missing")
    fi
    
    # Check service configuration
    if systemctl list-unit-files | grep -q "actions.runner"; then
        local service_name=$(systemctl list-unit-files | grep actions.runner | awk '{print $1}')
        if [ ! -d "/etc/systemd/system/${service_name}.d" ]; then
            issues+=("Systemd service override missing")
        fi
    fi
    
    # Check ownership
    local owner=$(stat -c %U "$runner_dir")
    if [ "$owner" != "root" ]; then
        issues+=("Runner directory owned by $owner (should be root)")
    fi
    
    if [ ${#issues[@]} -eq 0 ]; then
        print_status "ok" "No issues detected"
        return 0
    else
        print_status "warn" "Found ${#issues[@]} issue(s):"
        for issue in "${issues[@]}"; do
            echo "    • $issue"
        done
        return 1
    fi
}

# Function to fix existing runner
fix_runner() {
    local runner_dir="$1"
    
    print_header "🔧 Fixing Existing Runner"
    
    cd "$runner_dir"
    
    # Stop service
    print_step "⏸️  Stopping runner service..."
    if [ -f "./svc.sh" ]; then
        ./svc.sh stop 2>/dev/null || true
    fi
    
    # Fix ownership and permissions
    print_step "🔐 Fixing ownership and permissions..."
    chown -R root:root "$runner_dir"
    chmod -R 755 "$runner_dir"
    
    # Fix _diag directory (KEY FIX)
    print_step "📁 Fixing _diag directory..."
    mkdir -p "$runner_dir/_diag"
    chmod 777 "$runner_dir/_diag"
    print_status "ok" "_diag directory fixed (prevents log file errors)"
    
    # Create/fix _work directory
    mkdir -p "$runner_dir/_work"
    chmod 755 "$runner_dir/_work"
    
    # Fix .runner file
    if [ -f "$runner_dir/.runner" ]; then
        chmod 644 "$runner_dir/.runner"
    fi
    
    # Create/update .env file
    print_step "📝 Creating environment file..."
    cat > "$runner_dir/.env" << 'EOF'
RUNNER_ALLOW_RUNASROOT="1"
KUBECONFIG=/root/.kube/config
LANG=C.UTF-8
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
EOF
    
    # Ensure kubectl config exists
    if [ -f "/root/.kube/config" ]; then
        chmod 600 /root/.kube/config
        print_status "ok" "Kubeconfig found and accessible"
    else
        print_status "warn" "Kubeconfig not found - kubectl commands may fail"
    fi
    
    # Update systemd service
    print_step "🔄 Updating systemd service..."
    export RUNNER_ALLOW_RUNASROOT="1"
    
    local service_name=$(systemctl list-unit-files | grep actions.runner | awk '{print $1}')
    
    if [ -n "$service_name" ]; then
        mkdir -p "/etc/systemd/system/${service_name}.d"
        
        cat > "/etc/systemd/system/${service_name}.d/override.conf" << EOF
[Service]
User=root
Group=root
Environment="RUNNER_ALLOW_RUNASROOT=1"
Environment="KUBECONFIG=/root/.kube/config"
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
WorkingDirectory=${runner_dir}
UMask=0022
StandardOutput=journal
StandardError=journal
LimitCORE=infinity
EOF
        
        systemctl daemon-reload
        print_status "ok" "Service configuration updated"
    else
        print_status "warn" "Service not found, reinstalling..."
        ./svc.sh install root
    fi
    
    # Start service
    print_step "▶️  Starting runner service..."
    ./svc.sh start
    
    sleep 5
    
    return 0
}

# Function to install fresh runner
install_runner() {
    local runner_dir="$1"
    local repo_url="$2"
    local token="$3"
    local runner_name="$4"
    
    print_header "🚀 Installing Fresh Runner"
    
    # Install dependencies
    print_step "📦 Installing dependencies..."
    apt-get update -qq
    apt-get install -y -qq curl wget git libicu-dev
    
    # Create directory
    print_step "📁 Creating runner directory..."
    mkdir -p "$runner_dir"
    cd "$runner_dir"
    
    # Download latest runner
    print_step "⬇️  Downloading GitHub Actions runner..."
    local version=$(curl -s https://api.github.com/repos/actions/runner/releases/latest | grep tag_name | cut -d '"' -f 4 | sed 's/v//')
    print_status "info" "Version: $version"
    
    curl -sL "https://github.com/actions/runner/releases/download/v${version}/actions-runner-linux-x64-${version}.tar.gz" -o actions-runner.tar.gz
    tar xzf actions-runner.tar.gz
    rm actions-runner.tar.gz
    
    # Set permissions
    print_step "🔐 Setting up permissions..."
    chown -R root:root "$runner_dir"
    chmod -R 755 "$runner_dir"
    
    # Create _diag directory with proper permissions (KEY FIX)
    mkdir -p "$runner_dir/_diag"
    chmod 777 "$runner_dir/_diag"
    print_status "ok" "_diag directory created with proper permissions"
    
    # Create _work directory
    mkdir -p "$runner_dir/_work"
    chmod 755 "$runner_dir/_work"
    
    # Create environment file
    print_step "📝 Creating environment configuration..."
    cat > "$runner_dir/.env" << 'EOF'
RUNNER_ALLOW_RUNASROOT="1"
KUBECONFIG=/root/.kube/config
LANG=C.UTF-8
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
EOF
    
    # Configure runner
    print_step "⚙️  Configuring runner..."
    export RUNNER_ALLOW_RUNASROOT="1"
    
    ./config.sh \
        --url "$repo_url" \
        --token "$token" \
        --name "$runner_name" \
        --labels "self-hosted,kubernetes,Linux,X64" \
        --work "_work" \
        --unattended \
        --replace
    
    # Install as service
    print_step "🔧 Installing as system service..."
    ./svc.sh install root
    
    # Create service override
    local service_name=$(systemctl list-unit-files | grep actions.runner | awk '{print $1}')
    if [ -n "$service_name" ]; then
        mkdir -p "/etc/systemd/system/${service_name}.d"
        
        cat > "/etc/systemd/system/${service_name}.d/override.conf" << EOF
[Service]
User=root
Group=root
Environment="RUNNER_ALLOW_RUNASROOT=1"
Environment="KUBECONFIG=/root/.kube/config"
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
WorkingDirectory=${runner_dir}
UMask=0022
StandardOutput=journal
StandardError=journal
LimitCORE=infinity
EOF
        
        systemctl daemon-reload
    fi
    
    # Start service
    print_step "▶️  Starting runner service..."
    ./svc.sh start
    
    sleep 5
    
    return 0
}

# Function to completely reinstall
reinstall_runner() {
    local runner_dir="$1"
    local repo_url="$2"
    local token="$3"
    local runner_name="$4"
    
    print_header "🔄 Complete Reinstallation"
    
    # Remove old runner
    print_step "🗑️  Removing old runner..."
    if [ -d "$runner_dir" ]; then
        cd "$runner_dir"
        ./svc.sh stop 2>/dev/null || true
        ./svc.sh uninstall 2>/dev/null || true
        ./config.sh remove --token "$token" 2>/dev/null || true
        cd /
        rm -rf "$runner_dir"
    fi
    
    # Remove systemd services
    systemctl stop actions.runner.* 2>/dev/null || true
    systemctl disable actions.runner.* 2>/dev/null || true
    rm -f /etc/systemd/system/actions.runner.* 2>/dev/null || true
    rm -rf /etc/systemd/system/actions.runner.*.d 2>/dev/null || true
    systemctl daemon-reload
    
    print_status "ok" "Old runner removed"
    
    # Install fresh
    install_runner "$runner_dir" "$repo_url" "$token" "$runner_name"
    
    return 0
}

# Function to show final status
show_status() {
    local runner_dir="$1"
    
    print_header "📊 Final Status"
    
    cd "$runner_dir"
    
    echo "Service Status:"
    ./svc.sh status || true
    
    echo ""
    echo "Recent Logs:"
    journalctl -u actions.runner.* --no-pager -n 20 2>/dev/null || echo "No logs available yet"
    
    echo ""
    print_status "ok" "Runner setup complete!"
    echo ""
    echo "🔍 Verify runner connection:"
    echo "   Check GitHub: https://github.com/YOUR_ORG/YOUR_REPO/settings/actions/runners"
    echo ""
    echo "📋 Useful commands:"
    echo "   Status:  cd $runner_dir && sudo ./svc.sh status"
    echo "   Logs:    journalctl -u actions.runner.* -f"
    echo "   Stop:    cd $runner_dir && sudo ./svc.sh stop"
    echo "   Start:   cd $runner_dir && sudo ./svc.sh start"
    echo "   Restart: cd $runner_dir && sudo ./svc.sh stop && sudo ./svc.sh start"
    echo ""
}

# Main script
main() {
    print_header "🏃 GitHub Actions Runner Setup"
    
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then 
        print_status "error" "Please run as root (use sudo)"
        exit 1
    fi
    
    # Determine runner directory
    RUNNER_DIR="/opt/actions-runner"
    if [ -d "/root/actions-runner" ] && [ ! -d "$RUNNER_DIR" ]; then
        RUNNER_DIR="/root/actions-runner"
    fi
    
    # Check runner status
    print_step "🔍 Checking runner status..."
    check_runner_status "$RUNNER_DIR"
    status=$?
    
    case $status in
        0)
            print_status "ok" "Runner is installed and running at $RUNNER_DIR"
            diagnose_runner "$RUNNER_DIR"
            diag_result=$?
            
            if [ $diag_result -eq 0 ]; then
                print_status "ok" "Runner appears healthy!"
                echo ""
                read -p "Would you like to view the status anyway? (y/n): " view_status
                if [[ $view_status =~ ^[Yy]$ ]]; then
                    show_status "$RUNNER_DIR"
                fi
                exit 0
            fi
            
            echo ""
            echo "What would you like to do?"
            echo "  1) Fix existing runner (recommended)"
            echo "  2) Reinstall completely"
            echo "  3) Cancel"
            read -p "Choice [1-3]: " choice
            ;;
        3)
            print_status "warn" "Runner is configured but not running at $RUNNER_DIR"
            diagnose_runner "$RUNNER_DIR"
            echo ""
            echo "What would you like to do?"
            echo "  1) Fix and start runner (recommended)"
            echo "  2) Reinstall completely"
            echo "  3) Cancel"
            read -p "Choice [1-3]: " choice
            ;;
        2|4)
            print_status "warn" "Runner directory exists but not properly configured at $RUNNER_DIR"
            echo ""
            echo "What would you like to do?"
            echo "  1) Clean and reinstall (recommended)"
            echo "  2) Cancel"
            read -p "Choice [1-2]: " choice
            if [ "$choice" = "1" ]; then
                choice="2"  # Map to reinstall
            else
                choice="3"  # Map to cancel
            fi
            ;;
        1)
            print_status "info" "No runner found"
            choice="1"  # Fresh install
            ;;
    esac
    
    # Get user inputs if needed
    if [ "$choice" != "3" ]; then
        echo ""
        read -p "Enter GitHub repository URL (e.g., https://github.com/user/repo): " REPO_URL
        
        echo ""
        print_status "info" "Get a new token from: ${REPO_URL}/settings/actions/runners/new"
        read -p "Enter GitHub runner token: " TOKEN
        
        read -p "Enter runner name [self-hosted-runner]: " RUNNER_NAME
        RUNNER_NAME=${RUNNER_NAME:-self-hosted-runner}
    fi
    
    # Execute chosen action
    case $choice in
        1)
            if [ $status -eq 1 ]; then
                install_runner "$RUNNER_DIR" "$REPO_URL" "$TOKEN" "$RUNNER_NAME"
            else
                fix_runner "$RUNNER_DIR"
            fi
            show_status "$RUNNER_DIR"
            ;;
        2)
            echo ""
            print_status "warn" "This will completely remove and reinstall the runner!"
            read -p "Are you sure? (yes/no): " confirm
            if [ "$confirm" = "yes" ]; then
                reinstall_runner "$RUNNER_DIR" "$REPO_URL" "$TOKEN" "$RUNNER_NAME"
                show_status "$RUNNER_DIR"
            else
                print_status "info" "Cancelled"
                exit 0
            fi
            ;;
        3|*)
            print_status "info" "Cancelled"
            exit 0
            ;;
    esac
}

# Run main function
main "$@"

# Exit with success
exit 0