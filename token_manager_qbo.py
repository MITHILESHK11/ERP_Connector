import json
import os
import httpx
import base64
from datetime import datetime, timedelta

# ----------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------
TOKEN_FILE = ".qbo_tokens.json"
CLIENT_ID = "ABxPebIwzbRaODKkVsbTBGj8BH90STgYFCmKAbJRR9NHGBh2hf"
CLIENT_SECRET = "x9NloRqKmkNh5DkHjFqiS0ZTPj2zknNNwg1nOCfk"
REALM_ID = "9341457318163676"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"


# ----------------------------------------------------------------
# SAVE TOKENS
# ----------------------------------------------------------------
def save_tokens(access_token: str, refresh_token: str):
    """Save tokens to a local file."""
    data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "saved_at": datetime.now().isoformat()
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print("✅ QBO Tokens saved successfully!")


# ----------------------------------------------------------------
# LOAD TOKENS
# ----------------------------------------------------------------
def load_tokens():
    """Load tokens from file."""
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE, "r") as f:
        return json.load(f)


# ----------------------------------------------------------------
# CHECK IF TOKEN EXPIRED
# ----------------------------------------------------------------
def is_token_expired(saved_at: str) -> bool:
    """Check if token is older than 50 minutes (QBO tokens last 60 minutes)."""
    saved_time = datetime.fromisoformat(saved_at)
    return datetime.now() > saved_time + timedelta(minutes=50)


# ----------------------------------------------------------------
# REFRESH TOKEN AUTOMATICALLY
# ----------------------------------------------------------------
def refresh_access_token(refresh_token: str) -> str:
    """Use refresh token to get a new access token automatically."""
    print("🔄 QBO Token expired — refreshing automatically...")

    # QBO requires Basic Auth header with client_id:client_secret
    credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()

    response = httpx.post(
        TOKEN_URL,
        headers={
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    )
    response.raise_for_status()
    result = response.json()

    # Save new tokens (QBO also rotates refresh tokens)
    save_tokens(result["access_token"], result["refresh_token"])
    print("✅ QBO Token refreshed successfully!")
    return result["access_token"]


# ----------------------------------------------------------------
# GET VALID TOKEN — MAIN FUNCTION TO USE
# ----------------------------------------------------------------
def get_valid_token() -> str:
    """
    Get a valid QBO token automatically.
    - If token is still valid → return it
    - If token expired → refresh automatically using refresh token
    - No manual action needed!
    """
    tokens = load_tokens()

    if not tokens:
        print("❌ No QBO tokens found! Run setup first.")
        return None

    if is_token_expired(tokens["saved_at"]):
        return refresh_access_token(tokens["refresh_token"])

    print("✅ QBO Token is still valid!")
    return tokens["access_token"]


def get_realm_id() -> str:
    """Return the QBO Realm ID (acts as tenant_id)."""
    return REALM_ID


# ----------------------------------------------------------------
# SETUP — RUN THIS ONCE TO SAVE YOUR TOKENS
# ----------------------------------------------------------------
if __name__ == "__main__":
    print("💾 Saving your QBO tokens...")
    save_tokens(
        access_token="eyJhbGciOiJkaXIiLCJlbmMiOiJBMTI4Q0JDLUhTMjU2IiwieC5vcmciOiJIMCJ9..y1vwxbXwjDom5OKfVEKKaQ.ue5x2snd0TgejlQ-LI-SbxE2nVHayvW5wNJT8J71cUVU9I41yiMV6RC172gR1U8gl0pTdW72PKVGL1ddaJuwayXZChdFATjv-Gkh0-QkppCsZGb5sae-723nd40rD1ciCiftz62Aav_OFIWP6985nSIKGmVxBRdQ5gqhpoW0HI-EbBPccDrd9iiXEsRU_NGJkNc72jkDfsE9q9OavpfIff6qJuFyCoXh-jymMrWr33yLMNomJMQqZDhBPDb6XzdaHhmGpomiGTVsIROxz0-V8riKT6zddy6nFKrOzlSHDdXXQscfOV28J2Js2j5qCiF6_tna5daB5_DWuMekZnAkmoKBQZQeZEFarVTDm3qf-6P27HItEX6eo387hj3qQ0s7uUdtZi7tMzrDXUZAubxqV2iMDwBQQwzDa3lMcnlMa1GES_D4sBAjRlsF9XYrvHdCNpXo2vmnvsKagf6iiaX656F37t-0X_kPDIQb_rdQaAE.gazz_hbNau0H97zXnt0BZA",
        refresh_token="RT1-50-H0-1791521939zsri0vx459end8asqhsy"
    )

    print("\n🧪 Testing token...")
    token = get_valid_token()
    if token:
        print(f"\n✅ Everything working!")
        print(f"Token starts with: {token[:30]}...")
        print(f"Realm ID: {REALM_ID}")
