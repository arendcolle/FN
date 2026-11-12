"""Run one step: its row, its calls, its log lines and its traceback, all redacted."""
import logging
import logging.handlers
import traceback
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

from fn.config import Settings
from fn.contracts import CallKind, HttpClient, StepCall, StepRun
from fn.store import Store

if TYPE_CHECKING:
    from fn.llm import StructuredLLM

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

# Step log lines are stored at INFO even when no logging config has run.
logging.getLogger("fn").setLevel(logging.INFO)


@dataclass(frozen=True)
class StepContext:
    search_id: str
    store: Store
    llm: "StructuredLLM | None"
    http: HttpClient | None
    now: Callable[[], datetime]
    new_id: Callable[[], str]
    log: logging.Logger
    settings: Settings


def redact(text: str, secrets: Iterable[str]) -> str:
    """Replace every secret value in text with ***."""
    for secret in secrets:
        text = text.replace(secret, "***")
    return text


@dataclass
class CallRecorder:
    store: Store
    step_run_id: str
    secrets: list[str]
    calls: list[StepCall] = field(default_factory=list)
    model: str | None = None
    prompt_sha: str | None = None
    search_id: str = "-"
    step: str = "-"

    def record(
        self, kind: CallKind, request: str, duration_ms: int, *, status: int | None = None,
        response_sha: str | None = None, response_path: str | None = None, tokens_in: int | None = None,
        tokens_out: int | None = None, cost_usd: float | None = None, error: str | None = None,
        model: str | None = None, prompt_sha: str | None = None,
    ) -> StepCall:
        """Store one HTTP or LLM call of the running step, with request and error redacted.

        A model or prompt_sha passed here is written on the step row when the step ends.
        """
        call = StepCall(
            step_run_id=self.step_run_id, seq=len(self.calls) + 1, kind=kind,
            request=redact(request, self.secrets), status=status, duration_ms=duration_ms,
            response_sha=response_sha, response_path=response_path, tokens_in=tokens_in,
            tokens_out=tokens_out, cost_usd=cost_usd, error=redact(error, self.secrets) if error else None,
        )
        self.store.add_call(call)
        self.calls.append(call)
        self.model = model or self.model
        self.prompt_sha = prompt_sha or self.prompt_sha
        return call


@dataclass
class CallBuffer:
    """The calls of one fan_out task, kept in memory until the step thread writes them to the parent recorder."""
    parent: CallRecorder
    calls: list[tuple[tuple, dict]] = field(default_factory=list)

    @property
    def secrets(self) -> list[str]:
        return self.parent.secrets

    @property
    def search_id(self) -> str:
        return self.parent.search_id

    @property
    def step(self) -> str:
        return self.parent.step

    def record(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))

    def flush(self) -> None:
        """Write every kept call to the parent recorder, in the order the task made them."""
        for args, kwargs in self.calls:
            self.parent.record(*args, **kwargs)
        self.calls = []


_recorder: ContextVar[CallRecorder | CallBuffer | None] = ContextVar("fn_step_recorder", default=None)


def fan_out[T, R](fn: Callable[[T], R], items: Sequence[T], workers: int) -> list[R | Exception]:
    """fn(item) for each item on a pool of `workers` threads: its return value or exception, in item order.

    Each task records its calls in its own CallBuffer. Once every task has ended, the calling thread writes the
    buffers to its recorder in item order, also when a task raised, so seq follows item order.
    """
    if not items:
        return []
    parent = _recorder.get()
    buffers = [CallBuffer(parent) if parent else None for _ in items]
    results: list[R | Exception] = []
    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fn-fan-out") as pool:
            futures = []
            for item, buffer in zip(items, buffers):
                context = copy_context()
                context.run(_recorder.set, buffer)
                futures.append(pool.submit(context.run, fn, item))
            for future in futures:
                try:
                    results.append(future.result())
                except Exception as exc:  # noqa: BLE001 the caller gets every task's exception in item order
                    results.append(exc)
    finally:
        for buffer in filter(None, buffers):
            buffer.flush()
    return results


def current_recorder() -> CallRecorder | CallBuffer:
    """The call recorder of the step running in this context; raises RuntimeError outside a step."""
    recorder = _recorder.get()
    if recorder is None:
        raise RuntimeError("an outbound call was made outside a step")
    return recorder


def log_filter(secrets: Iterable[str]) -> Callable[[logging.LogRecord], bool]:
    """A handler filter that redacts the record and tags it with the running step's search id and name.

    The message is formatted and redacted, and an exception is turned into redacted text,
    so no formatter downstream sees a secret.
    """
    secrets = list(secrets)

    def apply(record: logging.LogRecord) -> bool:
        recorder = _recorder.get()
        record.search_id, record.step = (recorder.search_id, recorder.step) if recorder else ("-", "-")
        record.msg, record.args = redact(record.getMessage(), secrets), None
        if record.exc_info:
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)).rstrip(), secrets)
            record.exc_info = None
        return True

    return apply


def setup_logging(settings: Settings) -> None:
    """Send the root logger to var/log/fn.log (rotating) and stderr, redacted and tagged with search id and step."""
    settings.var_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    log_dir = settings.var_dir / "log"
    log_dir.mkdir(mode=0o700, exist_ok=True)
    handlers = [logging.handlers.RotatingFileHandler(log_dir / "fn.log", maxBytes=2_000_000, backupCount=5),
                logging.StreamHandler()]
    for handler in handlers:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s [%(search_id)s %(step)s] %(message)s"))
        handler.addFilter(log_filter(settings.secrets()))
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)


class _LogCapture(logging.Handler):
    def __init__(self, recorder: CallRecorder):
        super().__init__(logging.DEBUG)
        self.recorder = recorder
        self.lines: list[str] = []
        self.setFormatter(logging.Formatter(LOG_FORMAT))

    def emit(self, record: logging.LogRecord) -> None:
        recorder = _recorder.get()
        if recorder is self.recorder or getattr(recorder, "parent", None) is self.recorder:
            self.lines.append(redact(self.format(record), self.recorder.secrets))


def run_step[I: BaseModel, O: BaseModel](ctx: StepContext, name: str, fn: Callable[[StepContext, I], O], inp: I) -> O:
    """Run fn(ctx, inp) as step `name` of the context's search and return its output.

    The step row exists with status running before fn starts. On any exception the
    row gets status error, the redacted traceback and message, and the exception
    is raised again for the search lifecycle to handle.
    """
    secrets = ctx.settings.secrets()
    run = StepRun(
        id=ctx.new_id(), search_id=ctx.search_id, seq=ctx.store.next_step_seq(ctx.search_id), step=name,
        status="running", started_at=ctx.now(), input_model=type(inp).__name__,
    )
    ctx.store.start_step(run, redact(inp.model_dump_json(), secrets))
    recorder = CallRecorder(ctx.store, run.id, secrets, search_id=ctx.search_id, step=name)
    capture = _LogCapture(recorder)
    token = _recorder.set(recorder)
    logging.getLogger().addHandler(capture)
    status, out, output_json = "error", None, None
    error_type = error_message = error_traceback = None
    try:
        out = fn(ctx, inp)
        output_json = redact(out.model_dump_json(), secrets)
        status = "ok"
        return out
    except BaseException as exc:
        error_type, error_message = type(exc).__name__, redact(str(exc), secrets)
        error_traceback = redact(traceback.format_exc(), secrets)
        raise
    finally:
        logging.getLogger().removeHandler(capture)
        _recorder.reset(token)
        calls = recorder.calls
        ctx.store.finish_step(run.model_copy(update={
            "status": status,
            "ended_at": ctx.now(),
            "output_model": type(out).__name__ if out is not None else None,
            "error_type": error_type,
            "error_message": error_message,
            "traceback": error_traceback,
            "cost_usd": sum(c.cost_usd or 0.0 for c in calls),
            "tokens_in": sum(c.tokens_in or 0 for c in calls),
            "tokens_out": sum(c.tokens_out or 0 for c in calls),
            "model": recorder.model,
            "prompt_sha": recorder.prompt_sha,
            "log": "\n".join(capture.lines),
        }), output_json)


def skip_step[I: BaseModel, O: BaseModel](ctx: StepContext, name: str, inp: I, out: O) -> O:
    """Record step `name` as skipped, with inp as its input and out as the output it stands for, and return out."""
    secrets = ctx.settings.secrets()
    run = StepRun(
        id=ctx.new_id(), search_id=ctx.search_id, seq=ctx.store.next_step_seq(ctx.search_id), step=name,
        status="skipped", started_at=ctx.now(), ended_at=ctx.now(), input_model=type(inp).__name__,
        output_model=type(out).__name__,
    )
    ctx.store.start_step(run, redact(inp.model_dump_json(), secrets))
    ctx.store.finish_step(run, redact(out.model_dump_json(), secrets))
    return out
