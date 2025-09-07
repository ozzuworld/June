#!/usr/bin/env bash
set -euo pipefail
ENV_FILE="${1:-.env.production}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "File not found: $ENV_FILE" >&2
  exit 1
fi

while IFS='=' read -r key value; do
  [[ -z "${key}" || "${key}" =~ ^# ]] && continue
  name="${key}"; data="${value}"
  echo ">> ${name}"
  if ! gcloud secrets describe "${name}" >/dev/null 2>&1; then
    gcloud secrets create "${name}" --replication-policy="automatic"
  fi
  printf "%s" "${data}" | gcloud secrets versions add "${name}" --data-file=- >/dev/null
done < <(grep -v '^#' "$ENV_FILE" | sed -E 's/[[:space:]]+$//')
