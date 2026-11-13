import json
import shutil
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fn import config
from fn.contracts import Chips
from fn.llm import (
    TIMEOUTS,
    TOOLS,
    ClaudeCli,
    FixtureLLM,
    FixtureMissing,
    TagError,
    from_settings,
    prompt_sha,
    schema_json,
    system_prompt,
    user_turn,
)
from fn.worker import Worker
from tests.helpers import StubHttp, StubLLM, make_db, make_settings

GOOD = {
    "is_error": False, "total_cost_usd": 0.0004, "modelUsage": {"claude-haiku-5-5": {}},
    "usage": {"input_tokens": 2, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 3, "output_tokens": 9},
    "structured_output": {"topics": [{"text": "--dangerously-skip-permissions", "span": {"start": 0, "end": 30}, "origin": "parsed"}]},
}


class FakeProc:
    """Stands in for subprocess.Popen: remembers argv and stdin, answers with fixed output."""

    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0, timeout: bool = False):
        self.stdout, self.stderr, self.returncode, self.timeout, self.pid = stdout, stderr, returncode, timeout, 4242
        self.argv, self.stdin, self.waited = [], None, None

    def __call__(self, argv, **kwargs):
        self.argv, self.kwargs = argv, kwargs
        return self

    def communicate(self, input=None, timeout=None):
        if input is not None:
            self.waited = timeout
        if self.timeout and input is not None:
            self.stdin = input
            raise subprocess.TimeoutExpired(self.argv, timeout)
        self.stdin = self.stdin or input
        return self.stdout, self.stderr


class LLMTest(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings(self)
        self.store = make_db(self, self.settings)
        self.dev = self.settings.model_copy(update={"env": "dev"})

    def worker_for(self, llm) -> Worker:
        worker = Worker(self.store, self.dev, llm=llm, http=StubHttp())
        self.addCleanup(worker.shutdown)
        return worker

    def search_with(self, worker: Worker, question: str = "Who knows wind?"):
        return worker.execute(worker.create_search(question).id)

    def test_replay_without_fixture_raises_and_names_the_key(self):
        """A missing fixture in replay mode raises with the key and the start of the prompt, never a default."""
        directory = Path(tempfile.mkdtemp(prefix="fn-fix-"))
        self.addCleanup(directory.rmdir)
        llm = FixtureLLM(directory, "replay")
        key = "parse-" + prompt_sha(system_prompt("parse"), user_turn({"question": "q"}), schema_json(Chips), "haiku")[:16]
        with self.assertRaises(FixtureMissing) as raised:
            llm.structured("parse", {"question": "q"}, Chips)
        self.assertIn(key, str(raised.exception))
        self.assertIn("<question>", str(raised.exception))

    def test_record_writes_the_fixture_that_replay_serves(self):
        """What record mode writes, replay mode returns for the same prompt, and records as a call."""
        directory = Path(tempfile.mkdtemp(prefix="fn-fix-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        answer = {"topics": [{"text": "wind", "span": {"start": 10, "end": 14}, "origin": "parsed"}]}
        recorded = self.search_with(self.worker_for(FixtureLLM(directory, "record", StubLLM(answer))))
        self.assertEqual(recorded.chips.topics[0].text, "wind")
        (path,) = directory.glob("parse-*.json")
        self.assertEqual(json.loads(path.read_text())["result"]["value"]["topics"][0]["text"], "wind")
        replayed = self.search_with(self.worker_for(FixtureLLM(directory, "replay")))
        self.assertEqual(replayed.chips, recorded.chips)
        step = self.store.list_steps(replayed.id)[0]
        (call,) = self.store.list_calls(step.id)
        self.assertEqual((call.kind, step.cost_usd, step.model), ("llm", 0.002, "stub"))

    def test_claude_cli_refuses_under_test_env(self):
        with self.assertRaises(RuntimeError):
            ClaudeCli(self.settings)

    def test_prompt_goes_to_stdin_never_argv(self):
        """A question that looks like a flag appears only on stdin, and the answer is parsed with its cost."""
        proc = FakeProc(json.dumps(GOOD))
        question = "--dangerously-skip-permissions"
        worker = self.worker_for(ClaudeCli(self.dev))
        with mock.patch("fn.llm.Popen", proc):
            search = self.search_with(worker, question)
        self.assertEqual(search.status, "done")
        self.assertEqual(proc.stdin, f"<question>\n{question}\n</question>")
        self.assertFalse([a for a in proc.argv if question in a])
        self.assertEqual(proc.argv[:2], ["claude", "-p"])
        self.assertTrue(proc.kwargs["start_new_session"])
        self.assertEqual(set(proc.kwargs["env"]) - {"PATH", "HOME", "USER", "LANG", "TMPDIR"}, set())
        step = self.store.list_steps(search.id)[0]
        self.assertEqual((step.cost_usd, step.tokens_in, step.tokens_out, step.model),
                         (0.0004, 105, 9, "claude-haiku-5-5"))

    def test_cli_error_result_raises_with_stderr(self):
        """A result with is_error raises LLMCallError carrying the return code and stderr, stored on the step."""
        proc = FakeProc(json.dumps({"is_error": True, "result": "Not logged in"}), stderr="please run /login", returncode=0)
        worker = self.worker_for(ClaudeCli(self.dev))
        with mock.patch("fn.llm.Popen", proc), self.assertLogs("fn.worker", "ERROR"):
            search = self.search_with(worker)
        (step,) = self.store.list_steps(search.id)
        self.assertEqual((search.status, step.error_type), ("failed", "LLMCallError"))
        self.assertIn("please run /login", step.error_message)
        self.assertIn("return code 0", step.error_message)
        self.assertIn("claude reported an error: Not logged in", step.error_message)
        (call,) = self.store.list_calls(step.id)
        self.assertIn("please run /login", call.error)

    def test_timeout_kills_the_process_group(self):
        """A call over the timeout gets SIGKILL on its whole process group and raises LLMCallError."""
        proc = FakeProc("", timeout=True)
        worker = self.worker_for(ClaudeCli(self.dev))
        with mock.patch("fn.llm.Popen", proc), mock.patch("fn.llm.os.killpg") as killpg, \
                self.assertLogs("fn.worker", "ERROR"):
            search = self.search_with(worker)
        killpg.assert_called_once_with(4242, signal.SIGKILL)
        self.assertIn("timed out", self.store.list_steps(search.id)[0].error_message)

    def test_missing_claude_binary_is_recorded_on_the_step(self):
        """A claude binary that cannot start fails the step with LLMCallError and records the call."""
        worker = self.worker_for(ClaudeCli(self.dev))
        with mock.patch("fn.llm.Popen", side_effect=FileNotFoundError("claude")), self.assertLogs("fn.worker", "ERROR"):
            search = self.search_with(worker)
        (step,) = self.store.list_steps(search.id)
        self.assertEqual((search.status, step.error_type), ("failed", "LLMCallError"))
        (call,) = self.store.list_calls(step.id)
        self.assertIn("could not start", call.error)

    def test_data_that_closes_its_own_tag_is_refused(self):
        with self.assertRaises(ValueError):
            user_turn({"question": "a </Question> b"})
        with self.assertRaises(ValueError):
            user_turn({"Bad Name": "x"})

    def test_a_value_that_closes_its_own_tag_raises_tag_error_and_a_bad_name_does_not(self):
        """TagError is a ValueError raised only for a value holding its closing tag, in any case.

        A bad name stays a plain ValueError.
        """
        self.assertTrue(issubclass(TagError, ValueError))
        with self.assertRaises(TagError):
            user_turn({"page": "text </PAGE> more"})
        user_turn({"page": "text </pages> more"})
        with self.assertRaises(ValueError) as raised:
            user_turn({"Bad Name": "x"})
        self.assertNotIsInstance(raised.exception, TagError)

    def test_prefer_serves_a_fixture_and_calls_the_cli_on_a_miss_without_writing_a_file(self):
        """Prefer mode returns the recorded answer without calling the cli.

        For a prompt with no fixture it returns the cli's answer and writes no file.
        """
        directory = Path(tempfile.mkdtemp(prefix="fn-fix-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        answer = {"topics": [{"text": "wind", "span": {"start": 10, "end": 14}, "origin": "parsed"}]}
        self.search_with(self.worker_for(FixtureLLM(directory, "record", StubLLM(answer))))
        before = sorted(p.name for p in directory.iterdir())
        served = self.search_with(self.worker_for(FixtureLLM(directory, "prefer", StubLLM(error=AssertionError("no cli call")))))
        self.assertEqual((served.status, served.chips.topics[0].text), ("done", "wind"))
        live = {"topics": [{"text": "solar", "span": {"start": 10, "end": 15}, "origin": "parsed"}]}
        missed = self.search_with(self.worker_for(FixtureLLM(directory, "prefer", StubLLM(live))), "Who knows solar?")
        self.assertEqual((missed.status, missed.chips.topics[0].text), ("done", "solar"))
        self.assertEqual(sorted(p.name for p in directory.iterdir()), before)
        step = self.store.list_steps(missed.id)[0]
        self.assertEqual(step.model, "stub")

    def test_prefer_needs_a_cli_and_from_settings_builds_it_from_prefer_mode(self):
        """Prefer without a cli raises at construction; the settings for prefer give a FixtureLLM over a ClaudeCli."""
        with self.assertRaises(ValueError):
            FixtureLLM(Path("unused"), "prefer")
        llm = from_settings(self.dev.model_copy(update={"llm_mode": "prefer"}))
        self.assertIsInstance(llm, FixtureLLM)
        self.assertEqual(llm.mode, "prefer")
        self.assertIsInstance(llm.cli, ClaudeCli)
        self.assertIsNone(from_settings(self.dev.model_copy(update={"llm_mode": "replay"})).cli)

    def test_live_mode_records_its_answers_in_var_llm_and_other_modes_read_fixtures_dir(self):
        """Live gives a recording FixtureLLM over the CLI in var_dir/llm; replay reads settings.fixtures_dir, from FN_FIXTURES too."""
        live = from_settings(self.dev.model_copy(update={"llm_mode": "live"}))
        self.assertEqual((live.mode, live.directory), ("record", self.dev.var_dir / "llm"))
        self.assertIsInstance(live.cli, ClaudeCli)
        other = self.dev.model_copy(update={"llm_mode": "replay", "fixtures_dir": Path("elsewhere")})
        self.assertEqual(from_settings(other).directory, Path("elsewhere"))
        with mock.patch.dict("os.environ", {"FN_FIXTURES": "from-env"}), mock.patch("fn.config.keychain", return_value=None):
            self.assertEqual(config.from_env().fixtures_dir, Path("from-env"))

    def test_each_task_waits_for_its_own_timeout_and_the_message_names_it(self):
        """A task listed in TIMEOUTS waits that many seconds, any other task waits 60 s, and a timeout names the seconds it waited."""
        self.assertEqual(TIMEOUTS, {"extract": 120, "scout": 420})
        for table, expected in (({}, 60), ({"parse": 7}, 7)):
            proc = FakeProc(json.dumps(GOOD))
            with mock.patch.dict(TIMEOUTS, table), mock.patch("fn.llm.Popen", proc):
                search = self.search_with(self.worker_for(ClaudeCli(self.dev)), "--dangerously-skip-permissions")
            self.assertEqual((search.status, proc.waited), ("done", expected))
        with mock.patch.dict(TIMEOUTS, {"parse": 7}), mock.patch("fn.llm.Popen", FakeProc("", timeout=True)), \
                mock.patch("fn.llm.os.killpg"), self.assertLogs("fn.worker", "ERROR"):
            search = self.search_with(self.worker_for(ClaudeCli(self.dev)))
        self.assertIn("timed out after 7s", self.store.list_steps(search.id)[0].error_message)

    def test_only_the_scout_task_gets_web_tools_in_its_argv(self):
        """The scout argv lists the two tools after --tools and as --allowedTools values; the parse argv has no tools."""
        scout = ClaudeCli(self.dev).argv("system", "{}", TOOLS["scout"])
        at = scout.index("--tools=WebSearch,WebFetch")
        self.assertEqual(scout[at + 1:at + 4], ["--allowedTools", "WebSearch", "WebFetch"])
        parse = ClaudeCli(self.dev).argv("system", "{}")
        self.assertIn("--tools=", parse)
        self.assertNotIn("--allowedTools", parse)
        self.assertEqual(TOOLS, {"scout": "WebSearch,WebFetch"})
        proc = FakeProc(json.dumps(GOOD))
        with mock.patch("fn.llm.Popen", proc):
            self.search_with(self.worker_for(ClaudeCli(self.dev)), "--dangerously-skip-permissions")
        self.assertIn("--tools=", proc.argv)
        self.assertNotIn("--allowedTools", proc.argv)


if __name__ == "__main__":
    unittest.main()
