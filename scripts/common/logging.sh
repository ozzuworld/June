#!/bin/bash
# Common logging utilities for June Platform installation scripts

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
NC='\033[0m'

# Logging functions
log() { 
    echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"
}

success() { 
    echo -e "${GREEN}✅${NC} $1"
}

warn() { 
    echo -e "${YELLOW}⚠️${NC} $1"
}

error() { 
    echo -e "${RED}❌${NC} $1"
    exit 1
}

info() {
    echo -e "${CYAN}ℹ️${NC} $1"
}

debug() {
    if [ "${DEBUG:-false}" = "true" ]; then
        echo -e "${PURPLE}[DEBUG]${NC} $1"
    fi
}

# Progress indicators
show_progress() {
    local current="$1"
    local total="$2"
    local task="$3"
    local percent=$((current * 100 / total))
    
    echo -e "${CYAN}Progress: [$current/$total] ($percent%) - $task${NC}"
}

# Spinner for long-running operations
show_spinner() {
    local pid="$1"
    local message="$2"
    local delay=0.1
    local spinstr='|/-\'
    
    while [ "$(ps a | awk '{print $1}' | grep $pid)" ]; do
        local temp=${spinstr#?}
        printf " [%c] %s" "$spinstr" "$message"
        local spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\r"
    done
    printf "    \r"
}

# Section headers
header() {
    echo ""
    echo "==========================================="
    echo -e "${BLUE}$1${NC}"
    echo "==========================================="
    echo ""
}

subheader() {
    echo ""
    echo -e "${CYAN}--- $1 ---${NC}"
    echo ""
}

# Log with timestamp to file if LOG_FILE is set
log_to_file() {
    if [ -n "${LOG_FILE}" ]; then
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
    fi
}

# Combined log to console and file
log_both() {
    log "$1"
    log_to_file "$1"
}

# Export all functions
export -f log success warn error info debug show_progress show_spinner header subheader log_to_file log_both