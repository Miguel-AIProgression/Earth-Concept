from unittest.mock import patch, MagicMock
from exact_client import ExactClient


def test_refresh_token():
    client = ExactClient.__new__(ExactClient)
    client.client_id = "test_id"
    client.client_secret = "test_secret"
    client.token_file = "test_tokens.json"
    client.tokens = {"refresh_token": "old_refresh"}

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "new_access",
        "refresh_token": "new_refresh",
        "expires_in": 600,
    }

    with patch("requests.post", return_value=mock_resp):
        with patch("builtins.open", MagicMock()):
            with patch("json.dump"):
                token = client.refresh_token()

    assert token == "new_access"


def test_get_paginates():
    """Client moet __next links volgen voor alle resultaten."""
    client = ExactClient.__new__(ExactClient)
    client.base_url = "https://start.exactonline.nl/api/v1/2050702"
    client._access_token = "test"
    client.tokens = {"refresh_token": "r"}

    page1 = MagicMock()
    page1.status_code = 200
    page1.json.return_value = {
        "d": {
            "results": [{"OrderNumber": 1}, {"OrderNumber": 2}],
            "__next": "https://start.exactonline.nl/api/v1/2050702/next-page",
        }
    }
    page2 = MagicMock()
    page2.status_code = 200
    page2.json.return_value = {
        "d": {
            "results": [{"OrderNumber": 3}],
        }
    }

    with patch("requests.request", side_effect=[page1, page2]):
        results = client.get("/salesorder/SalesOrders")

    assert len(results) == 3
    assert results[2]["OrderNumber"] == 3


def test_retry_on_401():
    """Bij 401 moet de client refreshen en opnieuw proberen."""
    client = ExactClient.__new__(ExactClient)
    client.base_url = "https://start.exactonline.nl/api/v1/2050702"
    client._access_token = "expired"
    client.client_id = "id"
    client.client_secret = "secret"
    client.token_file = "test_tokens.json"
    client.tokens = {"refresh_token": "refresh"}

    resp_401 = MagicMock()
    resp_401.status_code = 401

    resp_ok = MagicMock()
    resp_ok.status_code = 200
    resp_ok.json.return_value = {"d": {"results": [{"Name": "test"}]}}

    refresh_resp = MagicMock()
    refresh_resp.status_code = 200
    refresh_resp.json.return_value = {
        "access_token": "new_token",
        "refresh_token": "new_refresh",
    }

    with patch("requests.request", side_effect=[resp_401, resp_ok]):
        with patch("requests.post", return_value=refresh_resp):
            with patch("builtins.open", MagicMock()):
                with patch("json.dump"):
                    results = client.get("/crm/Accounts")

    assert len(results) == 1
    assert results[0]["Name"] == "test"
