"""The one outbound HTTP client: timeouts, a size cap, http and https only, keys per host, call recording and the cache."""
import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote

import httpx

from fn.config import Settings
from fn.contracts import CacheMode
from fn.steps import current_recorder, redact

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MAX_BYTES = 5 * 1024 * 1024
MAX_RETRY_AFTER_S = 30
ERROR_BODY_CHARS = 300
OPENALEX_HOST = "api.openalex.org"
# Hosts that answer XML unless the request accepts JSON.
JSON_ONLY_WHEN_ASKED = ("pub.orcid.org",)
# Wikimedia refuses httpx's default agent; its policy asks for a name and a contact.
USER_AGENT = f"FN/0.1 (https://github.com/arendcolle/FN) httpx/{httpx.__version__}"


class HostKey(NamedTuple):
    header: str
    prefix: str
    field: str
    required: bool


# The only hosts that get a key, and only over https; a live call to a required one fails without it.
KEYS = {
    OPENALEX_HOST: HostKey("Authorization", "Bearer ", "openalex_api_key", False),
    "api.parallel.ai": HostKey("x-api-key", "", "parallel_api_key", True),
    "api.apify.com": HostKey("Authorization", "Bearer ", "apify_token", True),
}


class HttpError(RuntimeError):
    """An outbound call was refused, failed, returned a non-2xx status or missed the replay cache."""


class CacheMiss(HttpError):
    """The response cache holds no answer for a call that may not go out: replay mode, or cache="only"."""


class MissingKey(HttpError):
    """A live call to a host that needs a key, and the key is not set; raised before anything is sent."""


def retry_after(response: httpx.Response) -> float | None:
    """The Retry-After header in seconds; None when it is absent or not a number of seconds."""
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None


def cache_file(cache: Path, key: str) -> Path:
    """The cache file of a call key: the sha256 of the key, with .json."""
    return cache / f"{hashlib.sha256(key.encode()).hexdigest()}.json"


def cached_get(cache: Path, url: str) -> bytes | None:
    """The cached body of GET url in the cache folder, or None when it is not cached; makes no call."""
    path = cache_file(cache, str(httpx.URL(url)))
    return path.read_bytes() if path.exists() else None


class Client:
    """GET and POST. Live mode calls out and writes var/cache/<sha>.json; replay mode serves that cache and raises on a miss."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.settings = settings
        self.cache = settings.var_dir / "cache"
        self.sleep = sleep
        self.http = httpx.Client(transport=transport, timeout=TIMEOUT, follow_redirects=False,
                                 headers={"User-Agent": USER_AGENT})

    def _request(self, method: str, url: str, params: dict[str, str] | None, body: dict | None,
                 timeout_s: float | None) -> httpx.Request:
        timeout = TIMEOUT if timeout_s is None else httpx.Timeout(timeout_s, connect=TIMEOUT.connect)
        request = self.http.build_request(method, url, params=params, json=body, timeout=timeout)
        if request.url.host in JSON_ONLY_WHEN_ASKED:
            request.headers["Accept"] = "application/json"
        if request.url.scheme not in ("http", "https"):
            raise HttpError(f"refused {request.url.scheme} URL; http and https only")
        return request

    def _sign(self, request: httpx.Request) -> None:
        """Add the host's key header on https; raises MissingKey for a required key that is not set."""
        entry = KEYS.get(request.url.host)
        if entry is None:
            return
        key = getattr(self.settings, entry.field)
        if not key:
            if entry.required:
                raise MissingKey(f"no key for {request.url.host}; set {entry.field.upper()} or store it in the Keychain")
            return
        if request.url.scheme == "https":
            request.headers[entry.header] = entry.prefix + key.get_secret_value()

    def _read(self, request: httpx.Request) -> tuple[httpx.Response, bytes]:
        response = self.http.send(request, stream=True)
        try:
            body = bytearray()
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise HttpError(f"{request.method} {request.url} returned over {MAX_BYTES // (1024 * 1024)} MB")
        finally:
            response.close()
        return response, bytes(body)

    @staticmethod
    def _meta_cost(request: httpx.Request, body: bytes) -> float | None:
        if request.url.host != OPENALEX_HOST:
            return None
        try:
            return json.loads(body).get("meta", {}).get("cost_usd")
        except (ValueError, AttributeError):
            return None

    def _send(self, request: httpx.Request, shown: str, key: str, *, cost: Callable[[bytes], float | None] | None,
              keep: Callable[[bytes], bool] | None, cache: CacheMode) -> httpx.Response:
        """The one path for every call: the cache first when the mode asks for it, then the network with retries."""
        path = cache_file(self.cache, key)
        recorder = current_recorder()
        replay = self.settings.http_mode == "replay"
        if replay or cache != "refresh":
            served = "replay" if replay else "cache"
            if path.exists():
                body = path.read_bytes()
                recorder.record("http", f"{served} {shown}", 0, status=200, response_sha=hashlib.sha256(body).hexdigest(),
                                response_path=str(path), cost_usd=0.0)
                return httpx.Response(200, content=body, request=request)
            if replay or cache == "only":
                recorder.record("http", f"{served} {shown}", 0, error="not in the response cache")
                raise CacheMiss(f"replay: no cached response for {shown} ({path.name})")
        try:
            self._sign(request)
        except MissingKey as exc:
            recorder.record("http", shown, 0, error=str(exc))
            raise
        retry_on = (429, 503) if request.method == "GET" else (429,)
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
                sha = hashlib.sha256(body).hexdigest()
                try:
                    saved = keep is None or keep(body)
                    price = cost(body) if cost else self._meta_cost(request, body)
                except Exception as exc:
                    recorder.record("http", shown, ms, status=response.status_code, response_sha=sha,
                                    error=f"{type(exc).__name__}: {exc}")
                    raise
                if saved:
                    self.cache.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(dir=self.cache, suffix=".tmp", delete=False) as tmp:
                        tmp.write(body)
                    os.replace(tmp.name, path)
                recorder.record("http", shown, ms, status=response.status_code, response_sha=sha,
                                response_path=str(path) if saved else None, cost_usd=price)
                return httpx.Response(response.status_code, content=body, request=request)
            wait = retry_after(response) if response.status_code in retry_on else None
            error = f"{shown} returned {response.status_code}"
            if wait is not None:
                error += f"; Retry-After {wait:g}s" + (f" is over {MAX_RETRY_AFTER_S}s" if wait > MAX_RETRY_AFTER_S else "")
            if text := redact(body.decode(errors="replace"), self.settings.secrets())[:ERROR_BODY_CHARS].strip():
                error += f": {text}"
            recorder.record("http", shown, ms, status=response.status_code, error=error)
            if retried or wait is None or wait > MAX_RETRY_AFTER_S:
                raise HttpError(error)
            self.sleep(wait)
            retried = True

    def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        """GET url with params as a recorded call of the running step and return the 2xx response.

        A 429 or 503 with Retry-After up to 30 s is retried once after that wait. Raises HttpError
        for a refused URL, a non-2xx status (naming any longer wait), a body over 5 MB or a replay miss.
        """
        request = self._request("GET", url, params, None, None)
        shown = f"GET {unquote(str(request.url))}"
        return self._send(request, shown, str(request.url), cost=None, keep=None, cache="refresh")

    def post(self, url: str, body: dict, params: dict[str, str] | None = None, *, timeout_s: float | None = None,
             cost: Callable[[bytes], float | None] | None = None, keep: Callable[[bytes], bool] | None = None,
             cache: CacheMode = "refresh") -> httpx.Response:
        """POST body as JSON to url with params as a recorded call of the running step and return the 2xx response.

        cache is refresh (call out, write the cache), prefer (serve the cache, else call out) or only (never call
        out). cost(body) prices a live answer and keep(body) False leaves it uncached. timeout_s replaces the 30 s
        read timeout. Only a 429 is retried. Raises MissingKey, CacheMiss and HttpError as get does.
        """
        request = self._request("POST", url, params, body, timeout_s)
        shown = f"POST {unquote(str(request.url))} {json.dumps(body, ensure_ascii=False, separators=(',', ':'))}"
        key = f"POST {request.url}\n{json.dumps(body, sort_keys=True, separators=(',', ':'))}"
        return self._send(request, shown, key, cost=cost, keep=keep, cache=cache)
