from __future__ import annotations

import asyncio
import json
import logging
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from livekit.api.twirp_client import TwirpError

from src.livekit_room import build_room_token, ensure_room_ready
from src.settings import load_settings


LOGGER = logging.getLogger("interrupt.web")
SETTINGS = load_settings()
WEB_DIR = Path(__file__).resolve().parent / "web"


class PlaygroundHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def _json_response(self, payload: dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._json_response({"ok": True})
            return

        if parsed.path == "/defaults":
            identity = f"{SETTINGS.web.identity_prefix}-{os.getpid()}-{os.urandom(3).hex()}"
            room_name = f"{SETTINGS.web.room_name}-{os.urandom(3).hex()}"
            self._json_response(
                {
                    "room": room_name,
                    "identity": identity,
                    "ws_url": SETTINGS.livekit.url,
                }
            )
            return

        if parsed.path == "/token":
            params = parse_qs(parsed.query)
            room_name = params.get("room", [SETTINGS.web.room_name])[0].strip()
            identity = params.get("identity", [""])[0].strip()
            if not identity:
                identity = f"{SETTINGS.web.identity_prefix}-{os.getpid()}"
            try:
                asyncio.run(
                    ensure_room_ready(
                        SETTINGS,
                        room_name,
                        create_room=True,
                        dispatch_agent=True,
                        dispatch_metadata="explicit-dispatch-from-web-token",
                    )
                )
            except TwirpError as exc:
                LOGGER.error(
                    "agent dispatch 失败: room=%s code=%s status=%s message=%s",
                    room_name,
                    getattr(exc, "code", ""),
                    getattr(exc, "status", ""),
                    getattr(exc, "message", str(exc)),
                )
                self._json_response(
                    {"error": "dispatch_failed", "message": str(exc)},
                    status=502,
                )
                return
            except Exception as exc:
                LOGGER.exception("token 请求处理失败: room=%s", room_name)
                self._json_response(
                    {"error": "token_failed", "message": str(exc)},
                    status=500,
                )
                return
            token = build_room_token(SETTINGS, room_name, identity)
            LOGGER.info(
                "已生成 token: room=%s identity=%s agent=%s",
                room_name,
                identity,
                SETTINGS.agent.name,
            )
            self._json_response(
                {
                    "token": token,
                    "room": room_name,
                    "identity": identity,
                    "ws_url": SETTINGS.livekit.url,
                }
            )
            return

        super().do_GET()

    def log_message(self, format: str, *args) -> None:
        LOGGER.info("%s - %s", self.address_string(), format % args)


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, SETTINGS.logging.level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    server = ThreadingHTTPServer((SETTINGS.web.host, SETTINGS.web.port), PlaygroundHandler)
    LOGGER.info(
        "网页端已启动: http://%s:%s",
        SETTINGS.web.host,
        SETTINGS.web.port,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("网页端已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
