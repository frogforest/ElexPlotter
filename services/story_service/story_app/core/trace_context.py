import secrets
from contextvars import ContextVar
from typing import Any

traceparent_var: ContextVar[str | None] = ContextVar("traceparent", default=None)


class TraceContextMiddleware:
    """Propagate W3C Trace Context and expose the traceparent on every response."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        incoming = headers.get(b"traceparent", b"").decode("ascii", errors="ignore")
        valid = (
            len(incoming.split("-")) == 4
            and incoming.split("-")[0] == "00"
            and len(incoming.split("-")[1]) == 32
            and len(incoming.split("-")[2]) == 16
            and incoming.split("-")[3] in {"00", "01"}
        )
        traceparent = incoming if valid else f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"
        token = traceparent_var.set(traceparent)

        async def send_with_trace(message: dict) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers = [
                    (k, v) for k, v in response_headers if k.lower() != b"traceparent"
                ]
                response_headers.append((b"traceparent", traceparent.encode("ascii")))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace)
        finally:
            traceparent_var.reset(token)
