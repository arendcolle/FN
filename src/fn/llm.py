"""Structured LLM calls; every value in data reaches the model as tagged data."""
import contextlib
import hashlib
import json
import os
import re
import signal
import time
from pathlib import Path
from subprocess import PIPE, Popen, TimeoutExpired
from typing import Literal, Protocol

from pydantic import BaseModel

from fn.config import Settings
from fn.contracts import LLMResult
from fn.steps import current_recorder

PROMPTS = Path(__file__).parent / "prompts"
CLI_ENV = ("PATH", "HOME", "USER", "LANG", "TMPDIR")
TIMEOUT_S = 60
TIMEOUTS = {"extract": 120}
MODEL = "haiku"
DATA_NAME = re.compile(r"[a-z][a-z_]*")


class StructuredLLM(Protocol):
    def structured[T: BaseModel](self, task: str, data: dict[str, str], schema: type[T]) -> LLMResult[T]: ...


class LLMCallError(RuntimeError):
    """The Claude CLI failed; carries its return code (None on timeout), stderr and duration."""

    def __init__(self, message: str, returncode: int | None, stderr: str, duration_ms: int):
        super().__init__(f"{message} (return code {returncode}, {duration_ms} ms): {stderr.strip()[:500]}")
        self.returncode = returncode
        self.stderr = stderr
        self.duration_ms = duration_ms


class FixtureMissing(LookupError):
    """Replay mode found no fixture for the call."""


class TagError(ValueError):
    """A data value holds its own closing tag, so it could end its block early."""


def system_prompt(task: str) -> str:
    return (PROMPTS / f"{task}.md").read_text()


def user_turn(data: dict[str, str]) -> str:
    """One tagged block per data value; raises ValueError for a bad name and TagError for a value that closes its own tag."""
    blocks = []
    for name, value in data.items():
        if not DATA_NAME.fullmatch(name):
            raise ValueError(f"data name must be lowercase letters and underscores: {name!r}")
        if f"</{name}>" in value.lower():
            raise TagError(f"value of {name!r} contains its own closing tag")
        blocks.append(f"<{name}>\n{value}\n</{name}>")
    return "\n\n".join(blocks)


def prompt_sha(system: str, user: str, schema_text: str, model: str) -> str:
    """sha256 over the rendered prompt, the schema and the model, in that order."""
    return hashlib.sha256(f"{system}\0{user}\0{schema_text}\0{model}".encode()).hexdigest()


def schema_json(schema: type[BaseModel]) -> str:
    return json.dumps(schema.model_json_schema(), sort_keys=True)


class ClaudeCli:
    """Calls `claude -p` on the owner's subscription; the user turn goes to stdin, never argv."""

    def __init__(self, settings: Settings, model: str = MODEL):
        if settings.env == "test":
            raise RuntimeError("ClaudeCli refuses to run under FN_ENV=test; use FixtureLLM in replay mode")
        self.model = model

    def argv(self, system: str, schema_text: str) -> list[str]:
        return [
            "claude", "-p", "--model", self.model, "--output-format", "json", f"--json-schema={schema_text}",
            "--tools=", "--setting-sources=", "--strict-mcp-config", "--no-session-persistence",
            f"--system-prompt={system}",
        ]

    def structured[T: BaseModel](self, task: str, data: dict[str, str], schema: type[T]) -> LLMResult[T]:
        """Run the task prompt over data and return the schema-checked answer.

        Raises LLMCallError on a timeout, a non-zero exit, `is_error` or an answer without
        structured output; pydantic's ValidationError when the answer breaks the schema.
        """
        system, user, schema_text = system_prompt(task), user_turn(data), schema_json(schema)
        sha = prompt_sha(system, user, schema_text, self.model)
        recorder, started = current_recorder(), time.monotonic()
        timeout_s = TIMEOUTS.get(task, TIMEOUT_S)

        def fail(message: str, returncode: int | None, stderr: str) -> LLMCallError:
            ms = round((time.monotonic() - started) * 1000)
            error = LLMCallError(message, returncode, stderr, ms)
            recorder.record("llm", f"{task} {sha[:12]}: {user}", ms, status=returncode, error=str(error),
                            model=self.model, prompt_sha=sha)
            return error

        env = {k: os.environ[k] for k in CLI_ENV if k in os.environ}
        try:
            proc = Popen(
                self.argv(system, schema_text), stdin=PIPE, stdout=PIPE, stderr=PIPE,
                text=True, env=env, start_new_session=True,
            )
        except OSError as exc:
            raise fail("claude could not start", None, str(exc)) from exc
        try:
            stdout, stderr = proc.communicate(user, timeout=timeout_s)
        except TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            _, stderr = proc.communicate()
            raise fail(f"claude timed out after {timeout_s}s", None, stderr or "") from None
        try:
            payload = json.loads(stdout)
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            raise fail("claude printed no JSON result", proc.returncode, stderr or stdout)
        if payload.get("is_error") or proc.returncode != 0:
            raise fail(f"claude reported an error: {payload.get('result')}", proc.returncode, stderr)
        if payload.get("structured_output") is None:
            raise fail("claude result has no structured_output", proc.returncode, stderr or str(payload.get("result")))
        usage = payload.get("usage", {})
        tokens_in = sum(usage.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        model = next(iter(payload.get("modelUsage", {})), self.model)
        cost = float(payload.get("total_cost_usd", 0.0))
        ms = round((time.monotonic() - started) * 1000)
        recorder.record("llm", f"{task} {sha[:12]}: {user}", ms, status=proc.returncode, tokens_in=tokens_in,
                        tokens_out=usage.get("output_tokens", 0), cost_usd=cost, model=model, prompt_sha=sha)
        return LLMResult[schema](
            value=schema.model_validate(payload["structured_output"]), model=model, cost_usd=cost,
            tokens_in=tokens_in, tokens_out=usage.get("output_tokens", 0), billing="subscription",
        )


class FixtureLLM:
    """Replays recorded answers by prompt hash; in record mode it calls `cli` and writes the fixture.

    A fixture is tests/fixtures/llm/<task>-<sha16>.json. A missing fixture in replay mode raises.
    Prefer mode serves a fixture when one exists, else calls `cli`, and never writes a fixture.
    """

    def __init__(self, directory: Path, mode: Literal["record", "replay", "prefer"], cli: StructuredLLM | None = None):
        if mode in ("record", "prefer") and cli is None:
            raise ValueError(f"{mode} mode needs a cli to call")
        self.directory, self.mode, self.cli = directory, mode, cli
        self.model = getattr(cli, "model", MODEL)

    def structured[T: BaseModel](self, task: str, data: dict[str, str], schema: type[T]) -> LLMResult[T]:
        system, user, schema_text = system_prompt(task), user_turn(data), schema_json(schema)
        sha = prompt_sha(system, user, schema_text, self.model)
        key = f"{task}-{sha[:16]}"
        path = self.directory / f"{key}.json"
        if self.mode == "record":
            result = self.cli.structured(task, data, schema)
            self.directory.mkdir(parents=True, exist_ok=True)
            fixture = {"key": key, "task": task, "prompt": user, "result": result.model_dump(mode="json")}
            path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n")
            return result
        if not path.exists():
            if self.mode == "prefer":
                return self.cli.structured(task, data, schema)
            raise FixtureMissing(f"no LLM fixture {key}; prompt starts: {user[:200]!r}")
        result = LLMResult[schema].model_validate(json.loads(path.read_text())["result"])
        current_recorder().record(
            "llm", f"replay {key}: {user}", 0, status=0, tokens_in=result.tokens_in, tokens_out=result.tokens_out,
            cost_usd=result.cost_usd, model=result.model, prompt_sha=sha,
        )
        return result


def from_settings(settings: Settings) -> StructuredLLM:
    """The LLM for settings.llm_mode: the CLI when live, the fixture directory when recording, replaying or preferring."""
    if settings.llm_mode == "live":
        return ClaudeCli(settings)
    cli = ClaudeCli(settings) if settings.llm_mode in ("record", "prefer") else None
    return FixtureLLM(settings.root / "tests" / "fixtures" / "llm", settings.llm_mode, cli)
