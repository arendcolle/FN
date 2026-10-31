"""The search lifecycle on one worker thread, and the startup sweep."""
import logging
import subprocess
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from fn import search
from fn.config import Settings
from fn.contracts import ChipOrigin, Chips, HttpClient, Search
from fn.llm import StructuredLLM
from fn.steps import StepContext, redact
from fn.store import Store

log = logging.getLogger("fn.worker")


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


def code_state(root: Path) -> tuple[str | None, bool]:
    """The git sha of root and whether its tree has changes; (None, False) when git fails."""
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None, False
    return sha.stdout.strip(), bool(status.stdout.strip())


class Worker:
    def __init__(self, store: Store, settings: Settings, llm: StructuredLLM | None, http: HttpClient | None = None):
        self.store = store
        self.settings = settings
        self.llm = llm
        self.http = http
        self.boot_id = new_id()
        self.code_sha, self.dirty = code_state(settings.root)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fn-worker")

    def create_search(
        self, question: str, chips: Chips | None = None, chips_origin: ChipOrigin | None = None,
        rerun_of: str | None = None,
    ) -> Search:
        """Store a queued search stamped with this boot, the code state and the settings."""
        found = Search(
            id=new_id(), question=question, chips=chips, chips_origin=chips_origin, status="queued",
            created_at=now(), rerun_of=rerun_of, code_sha=self.code_sha, dirty=self.dirty,
            llm_mode=self.settings.llm_mode, boot_id=self.boot_id,
            settings_json=redact(self.settings.model_dump_json(), self.settings.secrets()),
        )
        self.store.create_search(found)
        return found

    def submit(self, search_id: str) -> Future[Search]:
        """Queue the search on the worker thread; an exception that escapes execute is logged redacted."""
        future = self.pool.submit(self.execute, search_id)
        future.add_done_callback(lambda done: self._log_escape(search_id, done))
        return future

    def _log_escape(self, search_id: str, done: Future[Search]) -> None:
        exc = done.exception()
        if exc is not None:
            error = redact("".join(traceback.format_exception(exc)), self.settings.secrets())
            log.error("search %s crashed outside its guard\n%s", search_id, error)

    def execute(self, search_id: str) -> Search:
        """Run one search to its end and return it.

        Any exception inside the run marks the search failed with the redacted traceback.
        Raises LookupError when no search has this id.
        """
        found = self.store.get_search(search_id)
        if found is None:
            raise LookupError(f"no search {search_id}")
        self.store.set_search_status(search_id, "running")
        ctx = StepContext(
            search_id=search_id, store=self.store, llm=self.llm, http=self.http, now=now, new_id=new_id,
            log=logging.getLogger("fn.step"), settings=self.settings,
        )
        try:
            search.run(ctx, found)
        except Exception:
            error = redact(traceback.format_exc(), self.settings.secrets())
            log.error("search %s failed\n%s", search_id, error)
            self.store.set_search_status(search_id, "failed", error=error, finished_at=now())
        else:
            self.store.set_search_status(search_id, "done", finished_at=now())
        return self.store.get_search(search_id)

    def sweep(self) -> list[str]:
        """Mark searches left queued or running by an earlier boot interrupted."""
        return self.store.sweep(self.boot_id, now())

    def shutdown(self) -> None:
        """Close the worker thread's connection, then wait for the pool to stop."""
        self.pool.submit(self.store.close)
        self.pool.shutdown(wait=True)
