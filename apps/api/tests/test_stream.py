"""PM stream: /ws snapshot + hub fan-out."""

from fastapi.testclient import TestClient

from app.main import app
from app.ws_hub import hub


def test_ws_hello_and_account_snapshot() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello"
            assert hello["payload"]["mode"] == "paper"
            types: list[str] = [hello["type"]]
            for _ in range(16):
                msg = ws.receive_json()
                types.append(msg["type"])
                if msg["type"] == "account":
                    assert "cash" in msg["payload"]
                    assert "equity" in msg["payload"]
                    break
            assert "account" in types


def test_ws_hub_publishes_ticker() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            for _ in range(16):
                msg = ws.receive_json()
                if msg["type"] == "account":
                    break
            hub.publish("ticker", {"symbol": "BTCUSDT", "price": 42_000.0, "ts": 9_999_001})
            for _ in range(20):
                incoming = ws.receive_json()
                if incoming["type"] == "ticker" and incoming["payload"].get("ts") == 9_999_001:
                    assert incoming["payload"]["symbol"] == "BTCUSDT"
                    assert incoming["payload"]["price"] == 42_000.0
                    return
            raise AssertionError("published ticker not received")
