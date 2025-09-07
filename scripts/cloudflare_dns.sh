#!/usr/bin/env bash
set -euo pipefail
REGION="${REGION:-us-central1}"
PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
DOMAIN="${1:?Usage: $0 <full.domain.name> <service-name>}"
SERVICE="${2:?Usage: $0 <full.domain.name> <service-name>}"

echo "[domain] mapping ${DOMAIN} -> ${SERVICE}"
if gcloud run domain-mappings describe --domain "${DOMAIN}" --region "${REGION}" >/dev/null 2>&1; then
  echo "[domain] exists"
else
  gcloud run domain-mappings create --service "${SERVICE}" --domain "${DOMAIN}" --region "${REGION}"
fi

echo "[domain] DNS records required:"
gcloud run domain-mappings describe --domain "${DOMAIN}" --region "${REGION}" --format=json | jq -r '.resourceRecords[] | [.name,.type,.rrdata] | @tsv'

# Optional Cloudflare upsert stub:
# curl -X POST "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE_ID}/dns_records" #   -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" -H "Content-Type: application/json" #   --data '{"type":"CNAME","name":"SUB.DOMAIN","content":"ghs.googlehosted.com","ttl":120,"proxied":false}'
