"""Herbruikbare Exact Online API client met token refresh en paginatie.

Tokens worden opgeslagen in Supabase (config tabel) zodat het script
stateloos kan draaien op GitHub Actions. Fallback naar lokaal bestand
voor lokale ontwikkeling.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from alerts import send_alert

load_dotenv()
log = logging.getLogger(__name__)

# Veiligheidsbuffer: refresh access_token als hij binnen X seconden verloopt.
EXPIRY_BUFFER_SECONDS = 60


def _supabase_client():
    """Maak een Supabase client als de env vars beschikbaar zijn."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if url and key:
        from supabase import create_client
        return create_client(url, key)
    return None


class ExactClient:
    TOKEN_URL = "https://start.exactonline.nl/api/oauth2/token"
    TOKEN_CONFIG_KEY = "exact_tokens"

    def __init__(self, token_file="exact_tokens.json"):
        self.client_id = os.getenv("EXACT_CLIENT_ID")
        self.client_secret = os.getenv("EXACT_CLIENT_SECRET")
        self.division = os.getenv("EXACT_DIVISION")
        self.token_file = token_file
        self._sb = _supabase_client()
        self.tokens = self._load_tokens()
        self.base_url = f"https://start.exactonline.nl/api/v1/{self.division}"
        self._access_token = self.tokens.get("access_token")

    def _load_tokens(self):
        """Laad tokens: eerst Supabase, dan lokaal bestand."""
        if self._sb:
            try:
                result = self._sb.table("config").select("value").eq(
                    "key", self.TOKEN_CONFIG_KEY
                ).execute()
                if result.data:
                    return result.data[0]["value"]
            except Exception:
                pass
        if os.path.exists(self.token_file):
            with open(self.token_file) as f:
                return json.load(f)
        return {}

    def _save_tokens(self, tokens):
        """Sla tokens op in Supabase + lokaal bestand als fallback.

        Voegt ``obtained_at`` toe zodat we proactief kunnen checken of de
        access_token bijna verloopt (voorkomt onnodige 401's).
        """
        tokens = dict(tokens)
        tokens.setdefault("obtained_at", datetime.now(timezone.utc).isoformat())
        if self._sb:
            try:
                self._sb.table("config").upsert({
                    "key": self.TOKEN_CONFIG_KEY,
                    "value": tokens,
                    "updated_at": "now()",
                }, on_conflict="key").execute()
            except Exception as e:
                log.warning("Tokens niet in Supabase opgeslagen: %s", e)
        try:
            with open(self.token_file, "w") as f:
                json.dump(tokens, f, indent=2)
        except OSError as e:
            log.warning("Tokens niet lokaal opgeslagen: %s", e)
        self.tokens = tokens

    def _reload_tokens(self):
        """Lees de nieuwste tokens opnieuw in uit de gedeelde opslag."""
        latest_tokens = self._load_tokens()
        if latest_tokens:
            self.tokens = latest_tokens
            self._access_token = latest_tokens.get("access_token", self._access_token)
        return latest_tokens

    def refresh_token(self):
        refresh_token = self.tokens.get("refresh_token")
        if not refresh_token:
            self._alert_refresh_dead("Geen refresh_token aanwezig in opslag.")
            raise RuntimeError("Geen refresh_token beschikbaar.")

        response = None
        for _ in range(2):
            response = requests.post(self.TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            })

            if response.status_code not in (400, 401):
                response.raise_for_status()
                new_tokens = response.json()
                self._save_tokens(new_tokens)
                self._access_token = new_tokens["access_token"]
                return self._access_token

            # 400/401: mogelijk race met parallelle refresh -> herlaad en retry.
            latest_tokens = self._reload_tokens()
            latest_refresh_token = latest_tokens.get("refresh_token") if latest_tokens else None
            if not latest_refresh_token or latest_refresh_token == refresh_token:
                break
            refresh_token = latest_refresh_token

        body = response.text[:500] if response is not None else "(geen response)"
        status = response.status_code if response is not None else "-"
        self._alert_refresh_dead(
            f"Exact refresh_token geweigerd (HTTP {status}).\n\n"
            f"Response body:\n{body}\n\n"
            "Actie vereist: voer exact_auth.py opnieuw uit om handmatig te re-authoriseren."
        )
        if response is not None:
            response.raise_for_status()
        raise RuntimeError("Token refresh mislukt.")

    def _alert_refresh_dead(self, detail: str):
        try:
            send_alert(
                subject="Exact Online token moet opnieuw geautoriseerd worden",
                body=(
                    "De Exact Online refresh_token is niet meer geldig; "
                    "de sync staat stil tot er opnieuw ingelogd wordt.\n\n"
                    f"{detail}\n"
                ),
            )
        except Exception as e:
            log.error("Alert versturen mislukt: %s", e)

    def _access_token_expired(self) -> bool:
        """True als de huidige access_token (bijna) verlopen is."""
        obtained = self.tokens.get("obtained_at")
        expires_in = self.tokens.get("expires_in")
        if not obtained or not expires_in:
            return True
        try:
            issued = datetime.fromisoformat(obtained)
            age = (datetime.now(timezone.utc) - issued).total_seconds()
            return age >= (int(expires_in) - EXPIRY_BUFFER_SECONDS)
        except (ValueError, TypeError):
            return True

    def _ensure_fresh_token(self):
        if not self._access_token or self._access_token_expired():
            # Herlaad eerst uit gedeelde opslag (misschien heeft een
            # parallelle run al ververst); zo niet, zelf refreshen.
            self._reload_tokens()
            if self._access_token_expired():
                self.refresh_token()

    def _headers(self):
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method, url, **kwargs):
        """Doe een request met retry bij 401/429."""
        self._ensure_fresh_token()
        for attempt in range(7):
            r = requests.request(method, url, headers=self._headers(), **kwargs)
            if r.status_code == 401:
                current_access_token = self._access_token
                latest_tokens = self._reload_tokens()
                latest_access_token = latest_tokens.get("access_token") if latest_tokens else None
                if latest_access_token and latest_access_token != current_access_token:
                    continue
                self.refresh_token()
                continue
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                wait = int(retry_after) if retry_after else min(5 * (2 ** attempt), 60)
                time.sleep(wait)
                continue
            if r.status_code >= 400:
                body_snippet = (r.text or "")[:800]
                log.error(
                    "Exact %s %s -> HTTP %s: %s",
                    method, url, r.status_code, body_snippet,
                )
            r.raise_for_status()
            return r
        if r.status_code >= 400:
            body_snippet = (r.text or "")[:800]
            log.error(
                "Exact %s %s -> HTTP %s (final): %s",
                method, url, r.status_code, body_snippet,
            )
        r.raise_for_status()
        return r

    def get(self, endpoint, params=None):
        """GET met automatische paginatie (Exact retourneert max 60 per page)."""
        url = f"{self.base_url}{endpoint}"
        all_results = []
        page = 0
        while url:
            r = self._request("GET", url, params=params)
            data = r.json()
            d = data.get("d", data)
            if isinstance(d, dict):
                all_results.extend(d.get("results", []))
                url = d.get("__next")
            else:
                all_results.extend(d if isinstance(d, list) else [])
                url = None
            params = None  # params zitten al in __next URL
            page += 1
            # Rate limiting: wacht tussen pagina's om 429 te voorkomen
            if url:
                time.sleep(1)
        return all_results

    def post(self, endpoint, payload):
        url = f"{self.base_url}{endpoint}"
        r = self._request("POST", url, json=payload)
        return r.json()
