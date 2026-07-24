#!/usr/bin/env bash
#
# refresh_qbo_token.sh
# =====================
# Refreshes a QuickBooks Online access token using pure curl — no browser,
# no Python, no running app required. QBO is NOT actually "web-only" for
# this step; that reputation only applies to the FIRST login (which does
# need a browser, same as Xero — that's an OAuth requirement, not a QBO
# quirk). Refreshing after that first login is a plain curl call, same
# shape as Xero's, just with HTTP Basic Auth instead of body params.
#
# IMPORTANT: QuickBooks rotates the refresh token on every single use — the
# old one is invalidated within ~24-26 hours of a new one being issued. This
# script always writes back the NEW refresh_token it receives. If you run
# this script from two places at once (e.g. this script AND the app's
# background refresh loop) with the same stored refresh_token, whichever
# refreshes second will fail with invalid_grant — pick ONE mechanism to be
# the source of truth.
#
# Usage:
#   ./scripts/refresh_qbo_token.sh
#   ./scripts/refresh_qbo_token.sh /path/to/.erp_tokens.json
#
# Requires: curl, jq
set -euo pipefail

TOKEN_FILE="${1:-.erp_tokens.json}"
QBO_TOKEN_URL="https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: 'jq' is required (sudo apt-get install jq / brew install jq)" >&2
  exit 1
fi

if [ ! -f "$TOKEN_FILE" ]; then
  echo "ERROR: $TOKEN_FILE not found. Run the app once and log in via /auth/qbo/login first." >&2
  exit 1
fi

REFRESH_TOKEN=$(jq -r '.quickbooks.refresh_token // empty' "$TOKEN_FILE")
CLIENT_ID=$(jq -r '.quickbooks.client_id // empty' "$TOKEN_FILE")
CLIENT_SECRET=$(jq -r '.quickbooks.client_secret // empty' "$TOKEN_FILE")
REALM_ID=$(jq -r '.quickbooks.tenant_id // empty' "$TOKEN_FILE")

if [ -z "$REFRESH_TOKEN" ] || [ -z "$CLIENT_ID" ] || [ -z "$CLIENT_SECRET" ]; then
  echo "ERROR: Missing refresh_token/client_id/client_secret in $TOKEN_FILE." >&2
  echo "Log in once via /auth/qbo/login (and /auth/setup for credentials) to populate it." >&2
  exit 1
fi

echo "Refreshing QuickBooks Online token..."

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$QBO_TOKEN_URL" \
  -u "${CLIENT_ID}:${CLIENT_SECRET}" \
  -H "Accept: application/json" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=refresh_token" \
  --data-urlencode "refresh_token=${REFRESH_TOKEN}")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [ "$HTTP_CODE" != "200" ]; then
  echo "ERROR: QBO refresh failed (HTTP $HTTP_CODE):" >&2
  echo "$BODY" >&2
  echo "" >&2
  echo "If this is 'invalid_grant': the refresh token has already been rotated" >&2
  echo "elsewhere (e.g. the app's own background refresh loop), or it's expired" >&2
  echo "after 100 days unused. You'll need to log in again via /auth/qbo/login." >&2
  exit 1
fi

NEW_ACCESS_TOKEN=$(echo "$BODY" | jq -r '.access_token')
NEW_REFRESH_TOKEN=$(echo "$BODY" | jq -r '.refresh_token')

# Write the NEW access + refresh token back, preserving realm_id/client creds.
TMP_FILE=$(mktemp)
jq --arg at "$NEW_ACCESS_TOKEN" \
   --arg rt "$NEW_REFRESH_TOKEN" \
   --arg saved_at "$(date -u +%Y-%m-%dT%H:%M:%S.%6N)" \
   '.quickbooks.access_token = $at | .quickbooks.refresh_token = $rt | .quickbooks.saved_at = $saved_at' \
   "$TOKEN_FILE" > "$TMP_FILE" && mv "$TMP_FILE" "$TOKEN_FILE"

echo "✅ QuickBooks Online token refreshed successfully."
echo "   Realm ID: $REALM_ID"
echo "   New access token saved (expires in ~60 min)."
echo "   New refresh token saved (old one will expire within ~24-26 hours — this is normal)."
