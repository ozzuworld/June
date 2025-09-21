#!/bin/bash
# setup-oracle-wallets.sh
# Script to download and combine Oracle wallet files for dual database setup

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠️ $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; exit 1; }

log "🔗 Oracle Dual Wallet Setup for June Platform"

# Check if wallet zip files exist
if [[ ! -f "harbordb_wallet.zip" ]]; then
    error "harbordb_wallet.zip not found. Please download Harbor database wallet first."
fi

if [[ ! -f "keycloakdb_wallet.zip" ]]; then
    error "keycloakdb_wallet.zip not found. Please download Keycloak database wallet first."
fi

log "📥 Found both wallet files"

# Clean up any existing oracle-wallet directory
if [[ -d "oracle-wallet" ]]; then
    warning "Removing existing oracle-wallet directory"
    rm -rf oracle-wallet
fi

# Create directories
mkdir -p oracle-wallet temp-harbor temp-keycloak

log "📦 Extracting wallet files..."

# Extract both wallets
unzip -q harbordb_wallet.zip -d temp-harbor/
unzip -q keycloakdb_wallet.zip -d temp-keycloak/

# Check if wallets are identical (common for same Oracle Cloud instance)
if diff -q temp-harbor/cwallet.sso temp-keycloak/cwallet.sso >/dev/null 2>&1; then
    log "🎯 Wallets are from same Oracle Cloud instance - using single wallet approach"
    
    # Copy all files from harbor wallet (either would work)
    cp temp-harbor/* oracle-wallet/
    
    # Verify both databases are in tnsnames.ora
    if grep -q "harbordb" oracle-wallet/tnsnames.ora && grep -q "keycloakdb" oracle-wallet/tnsnames.ora; then
        success "Both databases found in single wallet file"
    else
        warning "Single wallet doesn't contain both databases - will merge manually"
        
        # Merge tnsnames.ora files
        cat temp-harbor/tnsnames.ora > oracle-wallet/tnsnames.ora
        echo "" >> oracle-wallet/tnsnames.ora
        cat temp-keycloak/tnsnames.ora >> oracle-wallet/tnsnames.ora
        
        success "Merged tnsnames.ora files"
    fi
else
    log "🔗 Wallets are different - merging manually"
    
    # Use harbor wallet as base
    cp temp-harbor/* oracle-wallet/
    
    # Merge tnsnames.ora files
    cat temp-harbor/tnsnames.ora > oracle-wallet/tnsnames.ora
    echo "" >> oracle-wallet/tnsnames.ora
    cat temp-keycloak/tnsnames.ora >> oracle-wallet/tnsnames.ora
    
    success "Combined different wallet files"
fi

# Clean up temporary directories
rm -rf temp-harbor temp-keycloak

log "🧪 Verifying combined wallet..."

# Check required files exist
REQUIRED_FILES=("cwallet.sso" "ewallet.p12" "tnsnames.ora" "sqlnet.ora")
for file in "${REQUIRED_FILES[@]}"; do
    if [[ -f "oracle-wallet/$file" ]]; then
        success "$file ✓"
    else
        error "$file missing from wallet"
    fi
done

# Verify both databases are in tnsnames.ora
log "🔍 Checking database entries in tnsnames.ora..."

if grep -q "harbordb_high" oracle-wallet/tnsnames.ora; then
    success "Harbor database entry found"
else
    error "Harbor database entry missing from tnsnames.ora"
fi

if grep -q "keycloakdb_high" oracle-wallet/tnsnames.ora; then
    success "Keycloak database entry found"
else
    error "Keycloak database entry missing from tnsnames.ora"
fi

# Show database entries
log "📋 Available database connections:"
grep -E "^[a-zA-Z].*=" oracle-wallet/tnsnames.ora | sed 's/ =.*//' | while read -r db; do
    success "  $db"
done

# Test connections if sqlplus is available
if command -v sqlplus >/dev/null 2>&1; then
    log "🧪 Testing database connections..."
    
    export TNS_ADMIN="$(pwd)/oracle-wallet"
    
    # Test Harbor DB
    log "Testing Harbor database..."
    if echo "SELECT 'Harbor DB OK' FROM DUAL;" | sqlplus -S harbor_user/HarborPass123!@#@harbordb_high >/dev/null 2>&1; then
        success "Harbor database connection successful"
    else
        warning "Harbor database connection failed (check credentials)"
    fi
    
    # Test Keycloak DB
    log "Testing Keycloak database..."
    if echo "SELECT 'Keycloak DB OK' FROM DUAL;" | sqlplus -S keycloak_user/KeycloakPass123!@#@keycloakdb_high >/dev/null 2>&1; then
        success "Keycloak database connection successful"
    else
        warning "Keycloak database connection failed (check credentials)"
    fi
else
    warning "sqlplus not available - skipping connection tests"
fi

# Create GitHub Actions secrets (base64 encoded)
log "🔐 Creating GitHub Actions secrets format..."

cat > oracle-secrets.txt << EOF
# Add these to your GitHub repository secrets:

ORACLE_CWALLET_SSO="$(base64 -w 0 oracle-wallet/cwallet.sso)"
ORACLE_EWALLET_P12="$(base64 -w 0 oracle-wallet/ewallet.p12)"
ORACLE_TNSNAMES_ORA="$(base64 -w 0 oracle-wallet/tnsnames.ora)"
ORACLE_SQLNET_ORA="$(base64 -w 0 oracle-wallet/sqlnet.ora)"

# Database credentials
HARBOR_DB_PASSWORD="HarborPass123!@#"
KEYCLOAK_DB_PASSWORD="KeycloakPass123!@#"
EOF

success "GitHub Actions secrets saved to oracle-secrets.txt"

# Final summary
log ""
success "🎉 Oracle wallet setup completed successfully!"
log ""
log "📁 Files created:"
log "  oracle-wallet/          - Combined wallet directory"
log "  oracle-secrets.txt      - GitHub Actions secrets"
log ""
log "🚀 Next steps:"
log "  1. Review oracle-wallet/ directory contents"
log "  2. Add secrets from oracle-secrets.txt to GitHub"
log "  3. Run: ./deploy-oracle-enterprise.sh"
log ""
log "📋 Wallet contains connections to:"
grep -E "^[a-zA-Z].*=" oracle-wallet/tnsnames.ora | sed 's/ =.*//' | while read -r db; do
    log "  ✓ $db"
done

success "✅ Ready for enterprise deployment!"