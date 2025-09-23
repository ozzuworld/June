#!/bin/bash
# Fixed install-openvoice-tts.sh - Use available Python version

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="/opt/openvoice"
SERVICE_USER="openvoice"
SERVICE_GROUP="openvoice"
VENV_DIR="$INSTALL_DIR/venv"

# Logging function
log() {
    echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"
}

success() {
    echo -e "${GREEN}✅${NC} $1"
}

warning() {
    echo -e "${YELLOW}⚠️${NC} $1"
}

error() {
    echo -e "${RED}❌${NC} $1"
    exit 1
}

# Function to detect available Python version
detect_python() {
    for python_cmd in python3.12 python3.11 python3.10 python3.9 python3; do
        if command -v "$python_cmd" &> /dev/null; then
            PYTHON_CMD="$python_cmd"
            PYTHON_VERSION=$($python_cmd --version | cut -d' ' -f2 | cut -d'.' -f1-2)
            log "Found Python: $python_cmd (version $PYTHON_VERSION)"
            return 0
        fi
    done
    error "No suitable Python version found. Please install Python 3.9+ first."
}

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        error "This script must be run as root (use sudo)"
    fi
}

# Install system dependencies
install_system_deps() {
    log "Installing system dependencies..."
    
    apt-get update
    
    # Core dependencies
    apt-get install -y \
        python3 python3-dev python3-venv python3-pip \
        git wget curl build-essential \
        libsndfile1 ffmpeg espeak-ng \
        nginx supervisor htop unzip
    
    # Audio development libraries
    apt-get install -y \
        libasound2-dev portaudio19-dev \
        libportaudio2 libportaudiocpp0
    
    success "System dependencies installed"
}

# Create service user
create_service_user() {
    log "Creating service user..."
    
    if id "$SERVICE_USER" &>/dev/null; then
        success "Service user already exists: $SERVICE_USER"
    else
        useradd --system --home-dir "$INSTALL_DIR" --shell /bin/bash \
                --create-home --user-group "$SERVICE_USER"
        success "Created service user: $SERVICE_USER"
    fi
}

# Setup installation directory
setup_install_dir() {
    log "Setting up installation directory..."
    
    mkdir -p "$INSTALL_DIR"
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
}

# Clone OpenVoice repository
clone_openvoice() {
    log "Cloning OpenVoice repository..."
    
    if [ -d "$INSTALL_DIR/OpenVoice" ]; then
        log "OpenVoice repository already exists, updating..."
        cd "$INSTALL_DIR/OpenVoice"
        sudo -u "$SERVICE_USER" git pull
    else
        cd "$INSTALL_DIR"
        sudo -u "$SERVICE_USER" git clone https://github.com/myshell-ai/OpenVoice.git
    fi
}

# Setup Python virtual environment
setup_venv() {
    log "Setting up Python virtual environment..."
    
    # Remove existing venv if it exists
    if [ -d "$VENV_DIR" ]; then
        warning "Removing existing virtual environment..."
        rm -rf "$VENV_DIR"
    fi
    
    # Create new venv with detected Python version
    sudo -u "$SERVICE_USER" "$PYTHON_CMD" -m venv "$VENV_DIR"
    
    # Activate and upgrade pip
    sudo -u "$SERVICE_USER" bash -c "
        source '$VENV_DIR/bin/activate' && 
        pip install --upgrade pip setuptools wheel
    "
    
    success "Virtual environment created with $PYTHON_CMD"
}

# Install PyTorch with CUDA support
install_pytorch() {
    log "Installing PyTorch with CUDA support..."
    
    # Check if NVIDIA GPU is available
    if nvidia-smi &>/dev/null; then
        success "NVIDIA GPU detected, installing CUDA-enabled PyTorch"
        TORCH_INSTALL="torch torchaudio --index-url https://download.pytorch.org/whl/cu121"
    else
        warning "No NVIDIA GPU detected, installing CPU-only PyTorch"
        TORCH_INSTALL="torch torchaudio --index-url https://download.pytorch.org/whl/cpu"
    fi
    
    sudo -u "$SERVICE_USER" bash -c "
        source '$VENV_DIR/bin/activate' && 
        pip install $TORCH_INSTALL
    "
    
    success "PyTorch installed"
}

# Install OpenVoice dependencies
install_openvoice_deps() {
    log "Installing OpenVoice dependencies..."
    
    sudo -u "$SERVICE_USER" bash -c "
        source '$VENV_DIR/bin/activate' && 
        cd '$INSTALL_DIR/OpenVoice' &&
        pip install -e .
    "
    
    # Install additional dependencies
    sudo -u "$SERVICE_USER" bash -c "
        source '$VENV_DIR/bin/activate' && 
        pip install librosa soundfile numpy scipy fastapi uvicorn python-multipart
    "
    
    success "OpenVoice dependencies installed"
}

# Download model checkpoints
download_checkpoints() {
    log "Downloading model checkpoints..."
    
    CHECKPOINTS_DIR="$INSTALL_DIR/checkpoints_v2"
    mkdir -p "$CHECKPOINTS_DIR"
    
    cd "$CHECKPOINTS_DIR"
    
    # Download base models if they don't exist
    if [ ! -f "base_speakers/ses/en-default.pth" ]; then
        log "Downloading base speaker embeddings..."
        mkdir -p base_speakers/ses
        
        # You'll need to provide the actual URLs or copy the files manually
        warning "Please manually copy the OpenVoice v2 checkpoints to $CHECKPOINTS_DIR"
        warning "Required files:"
        warning "- base_speakers/ses/*.pth (speaker embeddings)"
        warning "- converter/config.json"
        warning "- converter/checkpoint.pth"
    fi
    
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$CHECKPOINTS_DIR"
}

# Install June TTS service
install_june_tts() {
    log "Installing June TTS service..."
    
    # Copy our FastAPI service code
    SERVICE_DIR="$INSTALL_DIR/june-tts-service"
    mkdir -p "$SERVICE_DIR"
    
    # Copy requirements.txt
    cat > "$SERVICE_DIR/requirements.txt" << 'EOF'
# June TTS Service Requirements
fastapi==0.104.1
uvicorn[standard]==0.24.0
python-multipart==0.0.6
pydantic==2.5.0
pydantic-settings==2.1.0
torch>=2.0.0
torchaudio>=2.0.0
librosa==0.10.1
soundfile==0.12.1
numpy>=1.24.0
scipy>=1.11.0
python-magic==0.4.27
httpx==0.25.2
aiofiles>=23.1.0
EOF

    # Install service requirements
    sudo -u "$SERVICE_USER" bash -c "
        source '$VENV_DIR/bin/activate' && 
        cd '$SERVICE_DIR' &&
        pip install -r requirements.txt
    "
    
    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$SERVICE_DIR"
    success "June TTS service installed"
}

# Create systemd service
create_systemd_service() {
    log "Creating systemd service..."
    
    cat > /etc/systemd/system/openvoice-tts.service << EOF
[Unit]
Description=OpenVoice TTS Service
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$INSTALL_DIR/june-tts-service
Environment=PATH=$VENV_DIR/bin
Environment=PYTHONPATH=$INSTALL_DIR/OpenVoice
ExecStart=$VENV_DIR/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=openvoice-tts

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl daemon-reload
    success "Systemd service created"
}

# Main installation function
main() {
    log "Starting OpenVoice TTS installation..."
    
    check_root
    detect_python
    install_system_deps
    create_service_user
    setup_install_dir
    clone_openvoice
    setup_venv
    install_pytorch
    install_openvoice_deps
    download_checkpoints
    install_june_tts
    create_systemd_service
    
    success "OpenVoice TTS installation completed!"
    
    echo -e "\n${GREEN}Next steps:${NC}"
    echo "1. Copy OpenVoice v2 checkpoints to $INSTALL_DIR/checkpoints_v2/"
    echo "2. Copy your FastAPI service code to $INSTALL_DIR/june-tts-service/"
    echo "3. Configure environment variables in /etc/systemd/system/openvoice-tts.service"
    echo "4. Start the service: sudo systemctl enable openvoice-tts && sudo systemctl start openvoice-tts"
    echo "5. Check logs: sudo journalctl -u openvoice-tts -f"
    
    log "Installation directory: $INSTALL_DIR"
    log "Service user: $SERVICE_USER"
    log "Python version: $PYTHON_VERSION"
    log "Virtual environment: $VENV_DIR"
}

# Run main function
main "$@"
