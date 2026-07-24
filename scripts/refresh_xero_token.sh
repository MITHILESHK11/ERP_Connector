#!/usr/bin/env bash
#
# refresh_xero_token.sh
# ======================
# Refreshes a Xero access token using pure curl — no browser, no Python,
# no running app required. Reads the current refresh_token/client_id/
# client_secret from .erp_tokens.json and writes the new (rotated) values
# back to the same file.
#
# IMPORTANT: Xero rotates the refresh token on every single use — the old
# one is invalidated the instant you use it. This script always writes back
# the NEW refresh_token it receives, never reuses the old one. If you run
# this script from two places at once (e.g. this script AND the app's
# background refresh loop) with the same stored refresh_token, whichever
# one refreshes second will fail with invalid_grant — pick ONE mechanism
# to be the source of truth, don't run both against the same tokens file.
#
# Usage:
#   ./scripts/refresh_xero_token.sh
#   ./scripts/refresh_xero_token.sh /path/to/.erp_tokens.json
#
# Requires: curl, jq
set -euo pipefail

TOKEN_FILE="${1:-.erp_tokens.json}"
XERO_TOKEN_URL="https://identity.xero.com/connect/token"

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: 'jq' is required (sudo apt-get install jq / brew install jq)" >&2
  exit 1
fi

if [ ! -f "$TOKEN_FILE" ]; then
  echo "ERROR: $TOKEN_FILE not found. Run the app once and log in via /auth/xero/login first." >&2
  exit 1
fi

REFRESH_TOKEN=$(jq -r '.xero.refresh_token // empty' "$TOKEN_FILE")
CLIENT_ID=$(jq -r '.xero.client_id // empty' "$TOKEN_FILE")
CLIENT_SECRET=$(jq -r '.xero.client_secret // empty' "$TOKEN_FILE")
TENANT_ID=$(jq -r '.xero.tenant_id // empty' "$TOKEN_FILE")

if [ -z "$REFRESH_TOKEN" ] || [ -z "$CLIENT_ID" ] || [ -z "$CLIENT_SECRET" ]; then
  echo "ERROR: Missing refresh_token/client_id/client_secret in $TOKEN_FILE." >&2
  echo "Log in once via /auth/xero/login (and /auth/setup for credentials) to populate it." >&2
  exit 1
fi

echo "Refreshing Xero token..."

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$XERO_TOKEN_URL" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=refresh_token" \
  --data-urlencode "refresh_token=${REFRESH_TOKEN}" \
  --data-urlencode "client_id=${CLIENT_ID}" \
  --data-urlencode "client_secret=${CLIENT_SECRET}")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [ "$HTTP_CODE" != "200" ]; then
  echo "ERROR: Xero refresh failed (HTTP $HTTP_CODE):" >&2
  echo "$BODY" >&2
  echo "" >&2
  echo "If this is 'invalid_grant': the refresh token has already been rotated" >&2
  echo "elsewhere (e.g. the app's own background refresh loop), or it's expired" >&2
  echo "after 60 days unused. You'll need to log in again via /auth/xero/login." >&2
  exit 1
fi

NEW_ACCESS_TOKEN=$(echo "$BODY" | jq -r '.access_token')
NEW_REFRESH_TOKEN=$(echo "$BODY" | jq -r '.refresh_token')

# Write the NEW access + refresh token back, preserving tenant_id/client creds.
TMP_FILE=$(mktemp)
jq --arg at "$NEW_ACCESS_TOKEN" \
   --arg rt "$NEW_REFRESH_TOKEN" \
   --arg saved_at "$(date -u +%Y-%m-%dT%H:%M:%S.%6N)" \
   '.xero.access_token = $at | .xero.refresh_token = $rt | .xero.saved_at = $saved_at' \
   "$TOKEN_FILE" > "$TMP_FILE" && mv "$TMP_FILE" "$TOKEN_FILE"

echo "✅ Xero token refreshed successfully."
echo "   Tenant ID: $TENANT_ID"
echo "   New access token saved (expires in ~30 min)."
echo "   New refresh token saved (old one is now invalid — this is normal)."
