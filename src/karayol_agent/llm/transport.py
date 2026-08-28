"""Bounded stdlib HTTP transport used by all LLM providers."""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Mapping, Protocol


class LLMTransportError(RuntimeError):
    pass


class LLMTransportTimeout(LLMTransportError):
    pass


@dataclass(frozen=True, slots=True)
class HTTPRequest:
    url: str
    headers: Mapping[str, str] = field(repr=False)
    body: bytes = field(repr=False)
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class HTTPResponse:
    status_code: int
    body: bytes = field(repr=False)


class HTTPTransport(Protocol):
    def send(self, request: HTTPRequest) -> HTTPResponse: ...


class UrllibHTTPTransport:
    def __init__(self, *, max_response_bytes: int = 256 * 1024) -> None:
        self.max_response_bytes = max_response_bytes

    def send(self, request: HTTPRequest) -> HTTPResponse:
        outgoing = urllib.request.Request(
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method="POST",
        )
        try:
            handlers: list[urllib.request.BaseHandler] = [_NoRedirectHandler()]
            try:
                import certifi
                import ssl
                ssl_context = ssl.create_default_context(cafile=certifi.where())
                handlers.append(urllib.request.HTTPSHandler(context=ssl_context))
            except Exception:
                pass
            opener = urllib.request.build_opener(*handlers)
            with opener.open(outgoing, timeout=request.timeout_seconds) as response:
                body = self._bounded_read(response)
                return HTTPResponse(status_code=response.status, body=body)
        except urllib.error.HTTPError as exc:
            body = self._bounded_read(exc)
            return HTTPResponse(status_code=exc.code, body=body)
        except (TimeoutError, socket.timeout) as exc:
            raise LLMTransportTimeout("LLM sağlayıcısı zaman aşımına uğradı.") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise LLMTransportTimeout("LLM sağlayıcısı zaman aşımına uğradı.") from exc
            raise LLMTransportError("LLM sağlayıcısına güvenli bağlantı kurulamadı.") from exc

    def _bounded_read(self, response: object) -> bytes:
        body = response.read(self.max_response_bytes + 1)  # type: ignore[attr-defined]
        if len(body) > self.max_response_bytes:
            raise LLMTransportError("LLM sağlayıcı yanıtı boyut sınırını aşıyor.")
        return body


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent API credentials from following redirects to another origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None
