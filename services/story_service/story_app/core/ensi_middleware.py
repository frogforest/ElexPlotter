import json
from typing import Any


class EnsiResponseMiddleware:
    """Wrap successful API JSON payloads in the ENSI data envelope."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        should_wrap = (
            path.startswith("/api/v1/")
            and scope.get("method") != "OPTIONS"
            and path not in {"/api/v1/health"}
        )
        if not should_wrap:
            await self.app(scope, receive, send)
            return

        response_start = None
        body = bytearray()

        async def capture(message: dict) -> None:
            nonlocal response_start
            if message["type"] == "http.response.start":
                response_start = message
            elif message["type"] == "http.response.body":
                body.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    await flush()

        async def flush() -> None:
            assert response_start is not None
            status_code = response_start["status"]
            headers = [
                (k, v)
                for k, v in response_start.get("headers", [])
                if k.lower() != b"content-length"
            ]
            payload = bytes(body)
            if 200 <= status_code < 300 and payload:
                try:
                    parsed = json.loads(payload)
                    if (
                        isinstance(parsed, dict)
                        and isinstance(parsed.get("data"), list)
                        and isinstance(parsed.get("meta"), dict)
                        and "pagination" not in parsed["meta"]
                    ):
                        old_meta = parsed["meta"]
                        wrapped = {
                            "data": parsed["data"],
                            "meta": {
                                "pagination": {
                                    "offset": (
                                        old_meta.get("offset")
                                        if old_meta.get("offset") is not None
                                        else max(old_meta.get("current_page", 1) - 1, 0)
                                        * old_meta.get("per_page", 20)
                                    ),
                                    "limit": old_meta.get("limit", old_meta.get("per_page", 20)),
                                    "total": old_meta.get("total", len(parsed["data"])),
                                    "type": "offset",
                                }
                            },
                        }
                    elif isinstance(parsed, dict) and "data" in parsed:
                        # Already an ENSI envelope: never wrap it a second time.
                        wrapped = parsed
                    else:
                        wrapped = {"data": parsed}
                    payload = json.dumps(
                        wrapped, ensure_ascii=False, separators=(",", ":")
                    ).encode()
                    headers.append((b"content-type", b"application/json"))
                except (ValueError, TypeError):
                    pass
            headers.append((b"content-length", str(len(payload)).encode()))
            response_start["headers"] = headers
            await send(response_start)
            await send({"type": "http.response.body", "body": payload})

        await self.app(scope, receive, capture)
