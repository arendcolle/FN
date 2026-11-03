"""The one outbound HTTP client: timeouts, a size cap, http and https only, call recording and the response cache."""
import hashlib
import json
import time
from collections.abc import Callable
from urllib.parse import unquote

import httpx

from fn.config import Settings
from fn.steps import current_recorder

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MAX_BYTES = 5 * 1024 * 1024
MAX_RETRY_AFTER_S = 30
OPENALEX_HOST = "api.openalex.org"
# Wikimedia refuses httpx's default agent; its policy asks for a name and a contact.
USER_AGENT = f"FN/0.1 (https://github.com/arendcolle/FN) httpx/{httpx.__version__}"


class HttpError(RuntimeError):
    """An outbound call was refused, failed, returned a non-2xx status or missed the replay cache."""


def retry_after(response: httpx.Response) -> float | None:
    """The Retry-After header in seconds; None when it is absent or not a number of seconds."""
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None


class Client:
    """GET only. Live mode calls out and writes var/cache/<sha>.json; replay mode serves that cache and raises on a miss."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.settings = settings
        self.cache = settings.var_dir / "cache"
        self.sleep = sleep
        self.http = httpx.Client(transport=transport, timeout=TIMEOUT, follow_redirects=False,
                                 headers={"User-Agent": USER_AGENT})

    def _request(self, url: str, params: dict[str, str] | None) -> httpx.Request:
        request = self.http.build_request("GET", url, params=params)
        if request.url.scheme not in ("http", "https"):
            raise HttpError(f"refused {request.url.scheme} URL; http and https only")
        key = self.settings.openalex_api_key
        if request.url.host == OPENALEX_HOST and request.url.scheme == "https" and key:
            request.headers["Authorization"] = f"Bearer {key.get_secret_value()}"
        return request

    def _read(self, request: httpx.Request) -> tuple[httpx.Response, bytes]:
        response = self.http.send(request, stream=True)
        try:
            body = bytearray()
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise HttpError(f"GET {request.url} returned over {MAX_BYTES // (1024 * 1024)} MB")
        finally:
            response.close()
        return response, bytes(body)

    @staticmethod
    def _cost(request: httpx.Request, body: bytes) -> float | None:
        if request.url.host != OPENALEX_HOST:
            return None
        try:
            return json.loads(body).get("meta", {}).get("cost_usd")
        except (ValueError, AttributeError):
            return None

    def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        """GET url with params as a recorded call of the running step and return the 2xx response.

        A 429 or 503 with Retry-After up to 30 s is retried once after that wait. Raises HttpError
        for a refused URL, a non-2xx status (naming any longer wait), a body over 5 MB or a replay miss.
        """
        request = self._request(url, params)
        shown = f"GET {unquote(str(request.url))}"
        sha = hashlib.sha256(str(request.url).encode()).hexdigest()
        path = self.cache / f"{sha}.json"
        recorder = current_recorder()
        if self.settings.http_mode == "replay":
            if not path.exists():
                recorder.record("http", f"replay {shown}", 0, error="not in the response cache")
                raise HttpError(f"replay: no cached response for {shown} ({path.name})")
            body = path.read_bytes()
            recorder.record("http", f"replay {shown}", 0, status=200, response_sha=hashlib.sha256(body).hexdigest(),
                            response_path=str(path), cost_usd=self._cost(request, body))
            return httpx.Response(200, content=body, request=request)
        retried = False
        while True:
            started = time.monotonic()
            try:
                response, body = self._read(request)
            except (httpx.HTTPError, HttpError) as exc:
                error = f"{type(exc).__name__}: {exc}"
                recorder.record("http", shown, round((time.monotonic() - started) * 1000), error=error)
                raise HttpError(f"{shown} failed: {error}") from exc
            ms = round((time.monotonic() - started) * 1000)
            if response.is_success:
                self.cache.mkdir(mode=0o700, parents=True, exist_ok=True)
                path.write_bytes(body)
                recorder.record("http", shown, ms, status=response.status_code,
                                response_sha=hashlib.sha256(body).hexdigest(), response_path=str(path),
                                cost_usd=self._cost(request, body))
                return httpx.Response(response.status_code, content=body, request=request)
            wait = retry_after(response) if response.status_code in (429, 503) else None
            error = f"{shown} returned {response.status_code}"
            if wait is not None:
                error += f"; Retry-After {wait:g}s" + (f" is over {MAX_RETRY_AFTER_S}s" if wait > MAX_RETRY_AFTER_S else "")
            recorder.record("http", shown, ms, status=response.status_code, error=error)
            if retried or wait is None or wait > MAX_RETRY_AFTER_S:
                raise HttpError(error)
            self.sleep(wait)
            retried = True
