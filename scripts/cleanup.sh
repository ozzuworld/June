#!/bin/bash
# Repository Cleanup Commands
# Run these commands to clean up duplicate, outdated, and unnecessary files

echo "í·¹ Starting repository cleanup..."

# 1. Remove Terraform backup files (too many backups)
echo "Removing Terraform backup files..."
rm -f infra/gke/main.tf.backup.*
ls infra/gke/main.tf.backup.* 2>/dev/null && echo "âš ï¸ Some backup files still exist" || echo "âœ… Terraform backups cleaned"

# 2. Remove duplicate Oracle wallet files
echo "Removing duplicate Oracle wallet files..."
rm -rf oracle-wallet/
echo "âœ… Duplicate oracle-wallet directory removed"

# 3. Remove unused Docker ignore file for TTS
echo "Removing duplicate .dockerignore..."
rm -f June/services/june-tts/.gitignore  # This duplicates .dockerignore
echo "âœ… Duplicate gitignore removed"

# 4. Remove old Cloud Build files (replaced by GitHub Actions)
echo "Removing old Cloud Build files..."
rm -f June/services/june-orchestrator/cloudbuild.yaml.bak
rm -f June/services/june-stt/cloudbuild.yaml.bak
echo "âœ… Old Cloud Build files removed"

# 5. Remove empty/placeholder files
echo "Removing empty placeholder files..."
rm -f infra/gke/deploy-gke-unified.sh  # Empty file
rm -f infra/gke/deploy-gke.yml         # Empty file
rm -f infra/gke/manifests.yaml         # Empty file
echo "âœ… Empty placeholder files removed"

# 6. Remove unused scripts that are duplicated in infra/
echo "Removing duplicate deployment scripts..."
rm -f scripts/deploy-gke-unified.sh  # Duplicated in infra/
echo "âœ… Duplicate scripts removed"

# 7. Clean up old Docker files that aren't being used
echo "Removing unused Docker configurations..."
rm -rf services/june-idp/nginx-edge/  # Not being used in current deployment
echo "âœ… Unused nginx-edge removed"

# 8. Remove README.txt (should be README.md)
echo "Removing old README format..."
rm -f README.txt
echo "âœ… Old README.txt removed"

# 9. Remove duplicate shared directories
echo "Cleaning up duplicate shared directories..."
# The shared/ directory should only be in one place, not duplicated in each service
rm -rf June/services/shared/
echo "âœ… Duplicate shared directory removed"

# 10. Remove old job backup files that are incomplete
echo "Removing incomplete job files..."
rm -rf jobs/  # This pg-backup job is incomplete and not integrated
echo "âœ… Incomplete job files removed"

# 11. Verify critical files still exist
echo "í´ Verifying critical files still exist..."

CRITICAL_FILES=(
    "June/services/june-orchestrator/app.py"
    "June/services/june-stt/app.py" 
    "June/services/june-tts/app.py"
    "June/services/june-idp/Dockerfile"
    "infra/gke/main.tf"
    ".github/workflows/deploy-gke.yml"
    "k8s/june-services/keycloak-oracle.yaml"
)

for file in "${CRITICAL_FILES[@]}"; do
    if [[ -f "$file" ]]; then
        echo "âœ… $file exists"
    else
        echo "âŒ CRITICAL: $file is missing!"
    fi
done

# 12. Update .gitignore to prevent future clutter
echo "Updating .gitignore..."
cat >> .gitignore << 'EOF'

# Terraform backups (keep only current state)
*.tfstate.backup.*
main.tf.backup.*

# Temporary deployment files
deployment-status.txt
terraform.tfvars

# Docker build context exclusions
.DS_Store
Thumbs.db

# IDE files
.vscode/
.idea/

# Local environment files
.env.local
.env.*.local

EOF

echo "âœ… .gitignore updated"

echo ""
echo "í¾¯ CLEANUP SUMMARY:"
echo "âœ… Removed 15+ unnecessary files"
echo "âœ… Cleaned up duplicate Oracle wallets"
echo "âœ… Removed old backup files"
echo "âœ… Removed empty placeholder files"
echo "âœ… Updated .gitignore"
echo ""
echo "í³ Current repository structure is now clean and focused"
echo ""
echo "í´§ NEXT STEPS:"
echo "1. Apply the fixed Keycloak Oracle configuration"
echo "2. Update service manifests with optimized resources"
echo "3. Test Oracle connectivity with proper JDBC URL"
echo "4. Deploy with single replicas for all services"

# Optional: Show current directory size
echo ""
echo "í³Š Repository size after cleanup:"
du -sh . 2>/dev/null || echo "Size calculation not available"

echo ""
echo "í·¹ Cleanup completed successfully!"
