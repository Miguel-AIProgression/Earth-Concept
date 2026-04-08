"""Herbruikbare Exact Online API client met token refresh en paginatie.

Tokens worden opgeslagen in Supabase (config tabel) zodat het script
stateloos kan draaien op GitHub Actions. Fallback naar lokaal bestand
voor lokale ontwikkeling.
"""

import json
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()


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
        """Sla tokens op in Supabase + lokaal bestand als fallback."""
        if self._sb:
            try:
                self._sb.table("config").upsert({
                    "key": self.TOKEN_CONFIG_KEY,
                    "value": tokens,
                    "updated_at": "now()",
                }, on_conflict="key").execute()
            except Exception:
                pass
        with open(self.token_file, "w") as f:
            json.dump(tokens, f, indent=2)
        self.tokens = tokens

    def refresh_token(self):
        r = requests.post(self.TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": self.tokens["refresh_token"],
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        })
        r.raise_for_status()
        new_tokens = r.json()
        self._save_tokens(new_tokens)
        self._access_token = new_tokens["access_token"]
        return self._access_token

    def _headers(self):
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method, url, **kwargs):
        """Doe een request met retry bij 401/429."""
        for attempt in range(5):
            r = requests.request(method, url, headers=self._headers(), **kwargs)
            if r.status_code == 401:
                self.refresh_token()
                continue
            if r.status_code == 429:
                wait = min(2 ** attempt, 30)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        r.raise_for_status()
        return r

    def get(self, endpoint, params=None):
        """GET met automatische paginatie (Exact retourneert max 60 per page)."""
        url = f"{self.base_url}{endpoint}"
        all_results = []
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
        return all_results

    def post(self, endpoint, payload):
        url = f"{self.base_url}{endpoint}"
        r = self._request("POST", url, json=payload)
        return r.json()
