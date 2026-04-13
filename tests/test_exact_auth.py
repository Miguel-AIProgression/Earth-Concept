from unittest.mock import patch, mock_open
import time
import pytest
from exact_auth import get_access_token, save_tokens


def test_geldig_token_niet_gerefreshed():
    tokens = {"access_token": "abc", "refresh_token": "r",
              "expires_at": time.time() + 600}
    with patch("exact_auth.load_tokens", return_value=tokens), \
         patch("exact_auth.refresh_access_token") as mock_refresh:
        assert get_access_token() == "abc"
        mock_refresh.assert_not_called()


def test_verlopen_token_wel_gerefreshed():
    tokens = {"access_token": "oud", "refresh_token": "r",
              "expires_at": time.time() - 10}
    new = {"access_token": "nieuw", "refresh_token": "r2",
           "expires_at": time.time() + 600}
    with patch("exact_auth.load_tokens", return_value=tokens), \
         patch("exact_auth.refresh_access_token", return_value=new):
        assert get_access_token() == "nieuw"


def test_geen_tokens_raises():
    with patch("exact_auth.load_tokens", return_value=None):
        with pytest.raises(RuntimeError, match="Geen tokens"):
            get_access_token()


def test_refresh_mislukt_raises():
    tokens = {"access_token": "oud", "refresh_token": "r", "expires_at": 0}
    with patch("exact_auth.load_tokens", return_value=tokens), \
         patch("exact_auth.refresh_access_token", return_value=None):
        with pytest.raises(RuntimeError, match="Refresh mislukt"):
            get_access_token()


def test_load_tokens_uit_supabase_als_file_niet_bestaat():
    from unittest.mock import MagicMock
    from exact_auth import load_tokens

    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"value": {"access_token": "from-sb", "refresh_token": "r"}}
    ]

    with patch("exact_auth._supabase_client", return_value=sb), \
         patch("exact_auth.os.path.exists", return_value=False):
        result = load_tokens()

    assert result == {"access_token": "from-sb", "refresh_token": "r"}


def test_save_tokens_zet_expires_at():
    tokens = {"access_token": "a", "refresh_token": "r", "expires_in": 600}
    before = time.time()
    captured = {}

    def fake_dump(obj, f, **kwargs):
        captured["tokens"] = obj

    with patch("exact_auth._supabase_client", return_value=None), \
         patch("builtins.open", mock_open()), \
         patch("exact_auth.json.dump", side_effect=fake_dump):
        save_tokens(tokens)

    assert "expires_at" in captured["tokens"]
    assert captured["tokens"]["expires_at"] > before
