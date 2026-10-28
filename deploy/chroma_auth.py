"""Chroma 앞에서 개인별 API 키의 해시를 검증하는 로컬 인증 서비스."""

import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import MappingProxyType


def load_key_hashes(path: Path):
    """비어 있거나 잘못된 키 파일은 거부한다."""
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, dict) or not values:
        raise ValueError("At least one API key hash is required")
    for name, digest in values.items():
        if not isinstance(name, str) or not name or not isinstance(digest, str):
            raise ValueError("Invalid API key hash entry")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("API key hashes must be SHA-256 hex digests")
    return MappingProxyType(values)


def make_handler(key_hashes):
    """인증 헤더를 로그나 응답에 포함하지 않고 키를 검증한다."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/verify":
                self.send_error(404)
                return
            header = self.headers.get("Authorization", "")
            scheme, _, token = header.partition(" ")
            valid = False
            if (
                scheme.lower() == "bearer"
                and token
                and not any(c.isspace() for c in token)
            ):
                digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
                for expected in key_hashes.values():
                    valid |= hmac.compare_digest(digest, expected)
            self.send_response(204 if valid else 401)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            if not valid:
                self.send_header("WWW-Authenticate", 'Bearer realm="IdeaLens"')
            self.end_headers()

        def log_message(self, *_args):
            pass

    return Handler


if __name__ == "__main__":
    hashes = load_key_hashes(Path(os.environ["CHROMA_AUTH_KEY_FILE"]))
    ThreadingHTTPServer(("127.0.0.1", 8010), make_handler(hashes)).serve_forever()
