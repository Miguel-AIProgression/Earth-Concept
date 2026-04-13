"""
Exact Online OAuth2 flow + test API calls.
Stap 1: Start script -> opent browser -> log in bij Exact
Stap 2: Kopieer de 'code' parameter uit de URL waar je op uitkomt
Stap 3: Plak de code in de terminal -> tokens worden opgeslagen + tests draaien
"""

import os
import json
import time
import webbrowser
import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("EXACT_CLIENT_ID")
CLIENT_SECRET = os.getenv("EXACT_CLIENT_SECRET")
REDIRECT_URI = os.getenv("EXACT_REDIRECT_URI")
DIVISION = os.getenv("EXACT_DIVISION")

AUTH_URL = "https://start.exactonline.nl/api/oauth2/auth"
TOKEN_URL = "https://start.exactonline.nl/api/oauth2/token"
API_BASE = f"https://start.exactonline.nl/api/v1/{DIVISION}"

TOKEN_FILE = "exact_tokens.json"
TOKEN_CONFIG_KEY = "exact_tokens"


def _supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if url and key:
        from supabase import create_client
        return create_client(url, key)
    return None


def save_tokens(tokens):
    # Voeg expires_at toe met 30s marge (expires_in is in seconden, default 600)
    tokens["expires_at"] = time.time() + int(tokens.get("expires_in", 600)) - 30
    sb = _supabase_client()
    if sb:
        try:
            sb.table("config").upsert({
                "key": TOKEN_CONFIG_KEY,
                "value": tokens,
                "updated_at": "now()",
            }, on_conflict="key").execute()
            print("Tokens ook opgeslagen in Supabase config")
        except Exception as e:
            print(f"Waarschuwing: tokens niet in Supabase opgeslagen: {e}")
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)
    print(f"Tokens opgeslagen in {TOKEN_FILE}")


def load_tokens():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return json.load(f)
    return None


def refresh_access_token(refresh_token):
    response = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })
    if response.status_code == 200:
        tokens = response.json()
        save_tokens(tokens)
        return tokens
    else:
        print(f"Token refresh mislukt: {response.status_code}")
        print(response.text)
        if response.status_code in (400, 401):
            try:
                from alerts import send_alert
                send_alert(
                    "Exact refresh_token verlopen",
                    f"Refresh mislukt ({response.status_code}):\n{response.text}\n\n"
                    "Run `python exact_auth.py` om opnieuw in te loggen.",
                )
            except Exception as e:
                print(f"Alert versturen mislukt: {e}")
        return None


def get_access_token():
    tokens = load_tokens()
    if not tokens:
        raise RuntimeError("Geen tokens — draai exact_auth.py handmatig voor eerste login")
    if tokens.get("expires_at", 0) > time.time():
        return tokens["access_token"]
    refreshed = refresh_access_token(tokens["refresh_token"])
    if not refreshed:
        raise RuntimeError("Refresh mislukt — refresh_token verlopen, handmatig opnieuw inloggen")
    return refreshed["access_token"]


def api_get(endpoint):
    token = get_access_token()
    if not token:
        return None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    url = f"{API_BASE}{endpoint}"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"API fout ({response.status_code}): {response.text[:500]}")
        return None


def test_connection():
    print("\n=== Test: Huidige divisie ophalen ===")
    result = api_get("/current/Me?$select=CurrentDivision,FullName")
    if result:
        data = result.get("d", {}).get("results", [{}])[0]
        print(f"  Ingelogd als: {data.get('FullName')}")
        print(f"  Divisie: {data.get('CurrentDivision')}")
        return True
    return False


def test_customers():
    print("\n=== Test: Eerste 5 klanten ophalen ===")
    result = api_get("/crm/Accounts?$select=ID,Name,Code&$top=5")
    if result:
        accounts = result.get("d", {}).get("results", [])
        for acc in accounts:
            print(f"  {acc.get('Code', '-'):>10} | {acc.get('Name')}")
        print(f"  ({len(accounts)} getoond)")
        return True
    return False


def test_products():
    print("\n=== Test: Eerste 5 producten ophalen ===")
    result = api_get("/logistics/Items?$select=ID,Code,Description&$top=5")
    if result:
        items = result.get("d", {}).get("results", [])
        for item in items:
            print(f"  {item.get('Code', '-'):>10} | {item.get('Description')}")
        print(f"  ({len(items)} getoond)")
        return True
    return False


def exchange_code(code):
    """Wissel autorisatiecode in voor tokens."""
    response = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })
    if response.status_code == 200:
        tokens = response.json()
        save_tokens(tokens)
        return tokens
    else:
        print(f"Fout bij token ophalen ({response.status_code}):")
        print(response.text)
        return None


if __name__ == "__main__":
    # Check of we al tokens hebben
    tokens = load_tokens()
    if tokens:
        print("Bestaande tokens gevonden, probeer te refreshen...")
        token = get_access_token()
        if token:
            print("Token geldig!")
            test_connection()
            test_customers()
            test_products()
            exit()

    # Stap 1: Open browser voor login
    auth_link = (
        f"{AUTH_URL}?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&force_login=0"
    )

    print("=" * 50)
    print("EXACT ONLINE KOPPELING")
    print("=" * 50)
    print(f"\nDe browser opent zo. Log in bij Exact Online.")
    print(f"Na het inloggen kom je op een pagina die niet laadt (example.com).")
    print(f"Dat is normaal! Kopieer de HELE URL uit je adresbalk en plak die hier.\n")

    webbrowser.open(auth_link)

    # Stap 2: Gebruiker plakt de redirect URL
    redirect_url = input("Plak hier de URL uit je adresbalk: ").strip()

    # Code uit URL halen
    if "code=" in redirect_url:
        code = redirect_url.split("code=")[1].split("&")[0]
    else:
        code = redirect_url  # Misschien hebben ze alleen de code geplakt

    print(f"\nCode ontvangen: {code[:20]}...")

    # Stap 3: Code inwisselen voor tokens
    tokens = exchange_code(code)
    if tokens:
        print("\n--- Verbinding gelukt! Tests starten... ---")
        test_connection()
        test_customers()
        test_products()
    else:
        print("\nKoppeling mislukt. Check de credentials in .env")
