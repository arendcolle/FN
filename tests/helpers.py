"""Shared test setup: a migrated temp database, test settings, a stub LLM, a stub HTTP client and recorded org facts."""
import atexit
import io
import json
import shutil
import tempfile
import unittest
import zipfile
from functools import cache
from pathlib import Path

import httpx
from pydantic import BaseModel, SecretStr

from fn import geo, net, orgjob, seedload
from fn.config import Settings
from fn.contracts import CacheMode, LLMResult, Search
from fn.steps import current_recorder
from fn.store import Store

SECRET = "sk-test-0123456789abcdef"
FIXTURES = Path(__file__).parent / "fixtures"


def make_settings(test: unittest.TestCase) -> Settings:
    var_dir = Path(tempfile.mkdtemp(prefix="fn-test-"))
    test.addCleanup(shutil.rmtree, var_dir, ignore_errors=True)
    return Settings(var_dir=var_dir, env="test", llm_mode="replay", http_mode="replay",
                    openalex_api_key=SecretStr(SECRET))


def make_db(test: unittest.TestCase, settings: Settings | None = None) -> Store:
    """A migrated Store in a temp dir, closed and removed after the test."""
    store = Store((settings or make_settings(test)).db_path)
    store.migrate()
    test.addCleanup(store.close)
    return store


def recorded_orgs(request: httpx.Request) -> httpx.Response:
    """Serve the ROR and Wikidata responses recorded in fixtures/http/ror and fixtures/http/wikidata; 404 for others."""
    if request.url.host == "api.ror.org":
        path = FIXTURES / "http" / "ror" / f"{request.url.path.rsplit('/', 1)[-1]}.json"
    else:
        params = request.url.params
        parts = [params.get("action"), params.get("ids") or params.get("entity"), params.get("property")]
        path = FIXTURES / "http" / "wikidata" / ("-".join(p for p in parts if p) + ".json")
    if not path.exists():
        return httpx.Response(404, json={"error": f"no fixture for {request.url}"})
    return httpx.Response(200, content=path.read_bytes())


def save_recorded_orgs(store: Store, settings: Settings, handler=recorded_orgs) -> Search:
    """Run the fn-orgs job over the alias file against the recorded responses, or handler; returns the ended job."""
    client = net.Client(settings.model_copy(update={"http_mode": "live"}), httpx.MockTransport(handler))
    return orgjob.refresh(store, settings, client)


@cache
def _seeded() -> Path:
    directory = Path(tempfile.mkdtemp(prefix="fn-seeded-"))
    atexit.register(shutil.rmtree, directory, ignore_errors=True)
    settings = Settings(var_dir=directory, env="test", llm_mode="replay", http_mode="replay")
    store = Store(settings.db_path)
    store.migrate()
    seedload.load(store)
    if (job := save_recorded_orgs(store, settings)).status != "done":
        raise RuntimeError(f"the recorded org facts did not load: {job.error}")
    store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store.close()
    return settings.db_path


def make_seeded_db(test: unittest.TestCase, settings: Settings | None = None) -> Store:
    """make_db with every seed row and the recorded org facts loaded; the load runs once per test process and is copied."""
    settings = settings or make_settings(test)
    shutil.copy(_seeded(), settings.db_path)
    return make_db(test, settings)


class StubLLM:
    """Answers every structured call with `answer`, or raises `error`, and records the call."""

    def __init__(self, answer: dict | None = None, error: Exception | None = None, cost_usd: float = 0.002):
        self.answer = answer or {}
        self.error = error
        self.cost_usd = cost_usd

    def structured[T: BaseModel](self, task: str, data: dict[str, str], schema: type[T]) -> LLMResult[T]:
        current_recorder().record("llm", f"{task}: {data}", 5, status=0, tokens_in=10, tokens_out=4,
                                  cost_usd=self.cost_usd, model="stub", prompt_sha="sha-stub")
        if self.error:
            raise self.error
        return LLMResult[schema](value=schema.model_validate(self.answer), model="stub", cost_usd=self.cost_usd,
                                 tokens_in=10, tokens_out=4, billing="stub")


@cache
def cities_zip() -> bytes:
    """The committed cities15000 extract, zipped as GeoNames serves the full dump."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.write(FIXTURES / "geo" / "cities15000-extract.txt", geo.CITIES_FILE)
    return out.getvalue()


class StubHttp:
    """Answers the GeoNames dump with the test extract, every other GET with an empty OpenAlex list and every POST
    with an empty result list; records each.

    A POST with cache="only" raises CacheMiss, as a client with an empty cache does.
    """

    def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        current_recorder().record("http", f"GET {url} {params or {}}", 1, status=200)
        if url == geo.CITIES_URL:
            return httpx.Response(200, content=cities_zip())
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []})

    def post(self, url: str, body: dict, params: dict[str, str] | None = None, *, timeout_s: float | None = None,
             cost=None, keep=None, cache: CacheMode = "refresh") -> httpx.Response:
        shown = f"POST {url} {params or {}} {json.dumps(body, sort_keys=True)}"
        if cache == "only":
            current_recorder().record("http", shown, 0, error="not in the response cache")
            raise net.CacheMiss(f"replay: no cached response for {shown}")
        current_recorder().record("http", shown, 1, status=200)
        return httpx.Response(200, json={"results": []})
