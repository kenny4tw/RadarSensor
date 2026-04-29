#!/usr/bin/env bash
# Complete Radar Sensor Installation Script for Raspberry Pi
# This script installs everything needed to run the radar daemon
# Usage: bash RPIradarinstall.sh
# 
# Requirements: 
#   - Raspberry Pi OS (Bookworm or newer)
#   - Internet connection
#   - ~500MB free disk space
#   - Sudo access (will be requested)

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="RadarSensor"
SERVICE_NAME="radar-daemon"
LOG_DIR="/var/log/radar_daemon"
VENV_DIR=".venv"

# Helper functions
print_header() {
    echo -e "\n${BLUE}=== $1 ===${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# Check if running on Raspberry Pi
check_rpi() {
    print_header "Checking Raspberry Pi"
    
    if [[ -f /sys/firmware/devicetree/base/model ]]; then
        RPI_MODEL=$(cat /sys/firmware/devicetree/base/model)
        print_success "Detected: $RPI_MODEL"
    else
        print_warning "Not detected as Raspberry Pi (but may still work on compatible hardware)"
    fi
    
    # Check Python version
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 not found. Will be installed in next step."
    else
        PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
        print_success "Python $PYTHON_VERSION available"
    fi
}

# Update system
update_system() {
    print_header "Updating System Packages"
    
    echo "Running apt update..."
    sudo apt update
    
    echo "Running apt upgrade..."
    sudo apt upgrade -y
    
    print_success "System updated"
}

# Install system dependencies
install_dependencies() {
    print_header "Installing System Dependencies"
    
    PACKAGES="python3 python3-pip python3-venv python3-dev git curl"
    
    echo "Installing: $PACKAGES"
    sudo apt install -y $PACKAGES
    
    print_success "System dependencies installed"
}

# Verify Python and pip
verify_python() {
    print_header "Verifying Python Environment"
    
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    print_success "Python version: $PYTHON_VERSION"
    
    PIP_VERSION=$(pip3 --version 2>&1 | awk '{print $2}')
    print_success "Pip version: $PIP_VERSION"
}

# Create and configure virtual environment
setup_venv() {
    print_header "Setting Up Python Virtual Environment"
    
    if [[ -d "$VENV_DIR" ]]; then
        print_warning "Virtual environment already exists at $VENV_DIR"
        read -p "Remove and recreate? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$VENV_DIR"
            print_info "Removed old virtual environment"
        else
            print_info "Using existing virtual environment"
            return 0
        fi
    fi
    
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    
    echo "Activating virtual environment..."
    source "$VENV_DIR/bin/activate"
    
    echo "Upgrading pip..."
    pip install --upgrade pip setuptools wheel
    
    print_success "Virtual environment created and activated"
}

# Install Python dependencies
install_python_deps() {
    print_header "Installing Python Dependencies"
    
    if [[ ! -f requirements.txt ]]; then
        print_error "requirements.txt not found in $SCRIPT_DIR"
        echo "Make sure you've cloned the repository correctly."
        exit 1
    fi
    
    echo "Installing packages from requirements.txt..."
    source "$VENV_DIR/bin/activate"
    pip install -r requirements.txt
    
    print_success "Python dependencies installed"
}

# Verify dependencies
verify_dependencies() {
    print_header "Verifying Installed Dependencies"
    
    source "$VENV_DIR/bin/activate"
    
    REQUIRED_PACKAGES=("acconeer" "scipy" "matplotlib" "flask")
    
    for package in "${REQUIRED_PACKAGES[@]}"; do
        if python3 -c "import ${package//-/_}" 2>/dev/null; then
            VERSION=$(pip show "$package" 2>/dev/null | grep Version | awk '{print $2}')
            print_success "$package: $VERSION"
        else
            print_warning "$package not found (may not be critical)"
        fi
    done
}

# Check for configuration file
check_config() {
    print_header "Checking Configuration"
    
    if [[ -f sensors_rpi.json ]]; then
        print_success "sensors_rpi.json found"
    else
        print_warning "sensors_rpi.json not found"
        print_info "You'll need to create or copy this file before starting the daemon"
    fi
    
    if [[ -f pi_radar_daemon.py ]]; then
        print_success "pi_radar_daemon.py found"
    else
        print_error "pi_radar_daemon.py not found in $SCRIPT_DIR"
        exit 1
    fi
}

# Make scripts executable
make_executable() {
    print_header "Making Scripts Executable"
    
    chmod +x pi_radar_daemon.py 2>/dev/null || true
    chmod +x run_radar_daemon_rpi.sh 2>/dev/null || true
    chmod +x setup_rpi.sh 2>/dev/null || true
    
    print_success "Scripts made executable"
}

# Setup systemd service
setup_service() {
    print_header "Setting Up Systemd Service"
    
    # Determine the service user
    SERVICE_USER="${SUDO_USER:-${USER:-pi}}"
    
    if ! id "$SERVICE_USER" >/dev/null 2>&1; then
        print_error "Cannot determine valid service user"
        exit 1
    fi
    
    print_info "Service user: $SERVICE_USER"
    
    # Create log directory
    echo "Creating log directory..."
    sudo mkdir -p "$LOG_DIR"
    sudo chown "$SERVICE_USER:$SERVICE_USER" "$LOG_DIR"
    sudo chmod 755 "$LOG_DIR"
    print_success "Log directory created: $LOG_DIR"
    
    # Create systemd service file
    echo "Creating systemd service file..."
    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
    
    sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Radar Sensor Daemon
After=network-online.target
Wants=network-online.target
Documentation=file://$SCRIPT_DIR/RASPBERRY_PI_SETUP.md

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$SCRIPT_DIR/run_radar_daemon_rpi.sh
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1
MemoryLimit=256M

[Install]
WantedBy=multi-user.target
EOF
    
    print_success "Service file created: $SERVICE_FILE"
    
    # Reload systemd daemon
    echo "Registering service with systemd..."
    sudo systemctl daemon-reload
    sudo systemctl enable "${SERVICE_NAME}.service"
    
    print_success "Service registered and enabled"
}

# Display post-installation instructions
show_instructions() {
    print_header "Installation Complete!"
    
    echo -e "${GREEN}All components have been installed successfully.${NC}\n"
    
    echo -e "${YELLOW}NEXT STEPS:${NC}"
    echo ""
    echo "1. CONFIGURE THE SENSOR:"
    echo "   Edit the configuration file to match your hardware setup:"
    echo "   nano $SCRIPT_DIR/sensors_rpi.json"
    echo ""
    echo "   Key settings:"
    echo "   - serial_port: USB device (e.g., /dev/ttyUSB0)"
    echo "   - mode: 'velocity' or 'distance'"
    echo "   - output_rate: measurements per second"
    echo "   - log_dir: $LOG_DIR"
    echo ""
    echo "2. FIND YOUR SENSOR PORT (if needed):"
    echo "   ls -la /dev/ttyUSB*     # USB adapters"
    echo "   ls -la /dev/ttyAMA*     # GPIO UART"
    echo ""
    echo "3. START THE DAEMON:"
    echo "   sudo systemctl start radar-daemon"
    echo ""
    echo "4. CHECK SERVICE STATUS:"
    echo "   sudo systemctl status radar-daemon"
    echo ""
    echo "5. VIEW LIVE LOGS:"
    echo "   sudo journalctl -u radar-daemon -f"
    echo ""
    echo "6. CHECK API STATUS (after starting):"
    echo "   curl http://localhost:8080/status | jq ."
    echo ""
    echo "MANAGEMENT COMMANDS:"
    echo "   Start:    sudo systemctl start radar-daemon"
    echo "   Stop:     sudo systemctl stop radar-daemon"
    echo "   Restart:  sudo systemctl restart radar-daemon"
    echo "   Status:   sudo systemctl status radar-daemon"
    echo ""
    echo "For more help, see: $SCRIPT_DIR/RASPBERRY_PI_SETUP.md"
    echo ""
}

# Main installation flow
main() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  RADAR SENSOR - RASPBERRY PI INSTALLATION SCRIPT      ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
    echo ""
    
    print_info "Installation directory: $SCRIPT_DIR"
    echo ""
    
    # Run installation steps
    check_rpi
    update_system
    install_dependencies
    verify_python
    setup_venv
    install_python_deps
    verify_dependencies
    check_config
    make_executable
    setup_service
    show_instructions
    
    echo -e "${GREEN}═════════════════════════════════════════════════════════${NC}"
    echo ""
}

# Run main installation
main
