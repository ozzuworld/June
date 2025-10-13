#!/bin/bash
# Make all installation scripts executable
# Run this after cloning the repository

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Making installation scripts executable..."

# Make this script executable first
chmod +x "$0"

# Make orchestrator executable
if [ -f "$SCRIPT_DIR/install-orchestrator.sh" ]; then
    chmod +x "$SCRIPT_DIR/install-orchestrator.sh"
    echo "✅ install-orchestrator.sh"
fi

# Make all phase scripts executable
if [ -d "$SCRIPT_DIR/install" ]; then
    for script in "$SCRIPT_DIR/install/"*.sh; do
        if [ -f "$script" ]; then
            chmod +x "$script"
            echo "✅ $(basename "$script")"
        fi
    done
fi

# Make common utilities executable (though they're sourced, not executed)
if [ -d "$SCRIPT_DIR/common" ]; then
    for script in "$SCRIPT_DIR/common/"*.sh; do
        if [ -f "$script" ]; then
            chmod +x "$script"
            echo "✅ common/$(basename "$script")"
        fi
    done
fi

# Make other scripts executable
for script in "$SCRIPT_DIR/"*.sh; do
    if [ -f "$script" ] && [ "$(basename "$script")" != "make-executable.sh" ]; then
        chmod +x "$script"
        echo "✅ $(basename "$script")"
    fi
done

echo ""
echo "🎉 All installation scripts are now executable!"
echo ""
echo "Usage:"
echo "  sudo ./scripts/install-orchestrator.sh              # Full installation"
echo "  sudo ./scripts/install-orchestrator.sh --help       # Show help"
echo "  sudo ./scripts/install-orchestrator.sh --skip phase1# Skip phases"
echo ""
echo "For more information, see scripts/README.md"