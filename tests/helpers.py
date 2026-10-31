"""Shared test setup: a migrated temp database, test settings, a stub LLM and a stub HTTP client."""
import atexit
import io
import shutil
import tempfile
import unittest
import zipfile
from functools import cache
from pathlib import Path

import httpx
from pydantic import BaseModel, SecretStr

from fn import geo, seedload
from fn.config import Settings
from fn.contracts import LLMResult
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


@cache
def _seeded() -> Path:
    directory = Path(tempfile.mkdtemp(prefix="fn-seeded-"))
    atexit.register(shutil.rmtree, directory, ignore_errors=True)
    store = Store(directory / "fn.sqlite3")
    store.migrate()
    seedload.load(store)
    store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store.close()
    return directory / "fn.sqlite3"


def make_seeded_db(test: unittest.TestCase, settings: Settings | None = None) -> Store:
    """make_db with every seed row loaded; the seed load runs once per test process and is copied."""
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
    """Answers the GeoNames dump with the test extract and every other GET with an empty OpenAlex list; records each."""

    def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        current_recorder().record("http", f"GET {url} {params or {}}", 1, status=200)
        if url == geo.CITIES_URL:
            return httpx.Response(200, content=cities_zip())
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []})
