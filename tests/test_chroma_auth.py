"""실제 HTTP 요청으로 키 누락·오류·정상·폐기를 검증한다."""

import hashlib
import http.client
import json
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest

from deploy.chroma_auth import load_key_hashes, make_handler


@pytest.fixture
def auth_server(tmp_path):
    path = tmp_path / "key-hashes.json"
    path.write_text(
        json.dumps({"member": hashlib.sha256(b"valid-test-token").hexdigest()})
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(load_key_hashes(path)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize(
    "token,status",
    [
        (None, 401),
        ("Bearer wrong-test-token", 401),
        ("Basic valid-test-token", 401),
        ("Bearer valid-test-token", 204),
        ("Bearer valid-test-token extra", 401),
    ],
)
def test_key_authorization(auth_server, token, status):
    connection = http.client.HTTPConnection(*auth_server, timeout=3)
    connection.request(
        "GET", "/verify", headers={"Authorization": token} if token else {}
    )
    response = connection.getresponse()
    assert response.status == status
    assert response.getheader("Cache-Control") == "no-store"
    assert response.read() == b""
    connection.close()


@pytest.mark.parametrize(
    "values",
    [{}, [], {"member": "plaintext-key"}, {"member": "f" * 63}, {"member": "g" * 64}],
)
def test_invalid_key_store_fails_closed(tmp_path, values):
    path = tmp_path / "keys.json"
    path.write_text(json.dumps(values))
    with pytest.raises(ValueError):
        load_key_hashes(path)


def test_removed_key_is_not_authorized():
    retained = {"member2": hashlib.sha256(b"another-test-key").hexdigest()}
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(retained))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = http.client.HTTPConnection(*server.server_address, timeout=3)
        client.request(
            "GET", "/verify", headers={"Authorization": "Bearer valid-test-token"}
        )
        assert client.getresponse().status == 401
        client.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
