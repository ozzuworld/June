#!/usr/bin/env bash
set -euo pipefail

: "${KC_BASE_URL:?missing}"
: "${KC_ADMIN:?missing}"
: "${KC_PASSWORD:?missing}"
REALM="${REALM:-june}"
CLIENT="${CLIENT:-gateway}"
REDIRECT="${REDIRECT:-https://example.com/*}"

export PATH="$PATH:/opt/keycloak/bin"

kcadm.sh config credentials --server "$KC_BASE_URL" --realm master --user "$KC_ADMIN" --password "$KC_PASSWORD"

# ensure realm
kcadm.sh get realms/$REALM >/dev/null 2>&1 || kcadm.sh create realms -s realm=$REALM -s enabled=true

# ensure client
kcadm.sh get clients -r $REALM -q clientId=$CLIENT | jq '.[0].id' -e >/dev/null 2>&1 ||   kcadm.sh create clients -r $REALM -s clientId=$CLIENT -s publicClient=false -s serviceAccountsEnabled=true -s 'redirectUris=["'"$REDIRECT"'"]'

CID=$(kcadm.sh get clients -r $REALM -q clientId=$CLIENT | jq -r '.[0].id')
kcadm.sh rotate-secret -r $REALM -s clientId=$CLIENT >/dev/null
SECRET=$(kcadm.sh get clients/$CID/client-secret -r $REALM | jq -r .value)

echo "client_id=$CLIENT"
echo "client_uuid=$CID"
echo "client_secret=$SECRET"
