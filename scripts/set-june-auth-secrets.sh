#!/usr/bin/env bash
# Add or rotate june-auth secrets (run after `terraform apply`).
set -euo pipefail

SVC_NAME=${1:-june-auth}

echo "Enter FERNET_KEY:"
read -r FERNET_KEY
echo "Enter MFA_JWT_SECRET:"
read -r MFA_JWT_SECRET

gcloud secrets versions add ${SVC_NAME}-fernet-key --data-file=- <<< "${FERNET_KEY}"
gcloud secrets versions add ${SVC_NAME}-mfa-jwt-secret --data-file=- <<< "${MFA_JWT_SECRET}"

echo "Done. Secrets updated."
