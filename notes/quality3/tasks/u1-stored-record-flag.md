# Task U1: the stored record behind a setting

## Goal

Every source page ends with "Show the stored record", a disclosure that holds the whole stored text of the page or record. For a web page that is up to 17,000 words of raw text, and for a record it is raw lines such as `display_name: ...`. Staff never need it to judge a fact: the sentence, the cite line, the passage and "Open the original page" already say what the source shows. It is a debugging aid. Decision U1: the source page shows the disclosure only when the setting `stored_record` is on, and it is off by default. `FN_STORED_RECORD=1` turns it on. Owner of the setting: `config.py`. Owner of the page: `staff.source_page`.

## What to build

### `src/fn/config.py`

- `Settings` gains `stored_record: bool = False`, after `scout`.
- `from_env` gains `"stored_record": env.get("FN_STORED_RECORD") == "1"`, the same rule as `FN_LINKEDIN` (config.py, the `linkedin_live` line). Only the exact text `1` turns it on.

### `src/fn/web/staff.py`

- `source_page(store, source, claim, back=None, stored_record: bool = False) -> str` (line 273). When `stored_record` is false the `h.details(... class_="fn-source__stored")` element (lines 301 and 302) becomes `None`, so nothing of it is rendered. When true the page is byte for byte what it is today. Nothing else on the page changes: `id="quote"` stays where it is, because it never sits on the stored text.
- The `stored` list (the text with the quote in `mark`) is built only when the disclosure is shown.
- Docstring first line: "A source in words staff can read: the person, the fact as a sentence, the passage, the link, and the stored text when stored_record is on."
- `show_source` (line 521), the only caller, passes `stored_record=worker_of(request).settings.stored_record`. `worker_of` is already imported (line 86) and `Worker.settings` is public (worker.py line 42). The debug router's `debug_source_page` is not a caller and does not change.

### `notes/e2e/design-system/STRINGS.md`

- Line 114 becomes: `- Disclosure: "Show the stored record", for debugging only: shown when FN runs with FN_STORED_RECORD=1, left out by default`.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Reading `FN_STORED_RECORD` into a setting | `config.from_env` |
| Whether the source page holds the disclosure | `staff.source_page` |
| Handing the setting to the page | `staff.show_source` |
| The words of the disclosure and when it shows | the design system, mirrored in `STRINGS.md` |

## Inputs a real run will meet

- `FN_STORED_RECORD` unset, `0`, `true`, empty: off. `1`: on.
- A web page source of 17,000 words, off: the page holds the passage only, so no raw text reaches the browser.
- A source opened without a claim, off: the page holds the title and, for a non-`fn:` url, the link. Nothing else.
- An import row (`fn:` url) without a claim, off: the title alone.
- Text with markup (`<script>`), off: it is not on the page at all; on: escaped as today.
- A source with empty text, on: an empty `pre` as today.

## Tests (each must fail without the change)

All in `tests/test_source_page.py`, with made-up names only.

- `test_the_stored_record_is_left_out_when_the_setting_is_off`: a second client built in the test with `create_app(self.settings.model_copy(update={"stored_record": False}), StubLLM(error=AssertionError("no LLM")), StubHttp())` on the same store, used inside `with`. A page source of `SENTENCE * 20 + quote + ". " + SENTENCE * 20` with a claim: the page holds no `fn-source__stored`, no "Show the stored record", and its lead, cite and passage are as on the client with the setting on; `html.count('id="quote"')` is 1. The same source opened without a claim and a record source with a claim also hold no `fn-source__stored`. A source with `<script>x</script>` in its text, off: the page holds no `x</script>` in any form, escaped or not.
- `test_fn_stored_record_turns_the_setting_on_only_for_1`: for `(None, False), ("0", False), ("true", False), ("", False), ("1", True)`, under `mock.patch.dict("os.environ", env, clear=True)` and `mock.patch("fn.config.keychain", return_value=None)` (the pattern of `tests/test_scout.py` line 124), `config.from_env().stored_record` equals the expected value. Also `make_settings(self).stored_record` is False.

## Existing tests that change, approved by the lead

- `SourcePageTest.setUp` in `tests/test_source_page.py`: `self.settings = make_settings(self)` becomes `self.settings = make_settings(self).model_copy(update={"stored_record": True})`. Every test of the class then runs with the setting on and keeps its expectation unchanged: `test_a_page_source_names_the_person_says_the_fact_and_holds_the_text_in_a_closed_record` still finds the disclosure, `test_a_very_long_source_shows_at_most_200_words_outside_the_stored_record` and `test_hostile_title_url_and_text_are_escaped` still check the stored text. No assertion changes.

No other existing test may change. Tests in `test_person_content.py`, `test_way_back.py` and `test_web.py` open `/sources/...` with the default (off) settings and read only the lead, the cite, the back link or the status code; they must pass untouched. Stop and report any that fails.

## Recorded model answers and replay (S6)

No prompt changes and no model call is added or removed, so no recorded answer gets a new key and no replay test changes. New searches store one more field, `"stored_record": false`, in `settings_json`; nothing reads that field, and stored searches keep their settings text.

## Hand check

`uv run python -m unittest` all green. Then, replay modes only and no server:

```
for flag in 0 1; do FN_VAR=$(mktemp -d) FN_LLM=replay FN_HTTP=replay FN_STORED_RECORD=$flag uv run python - <<'EOF'
from unittest import mock
from fastapi.testclient import TestClient
from fn import config
from fn.contracts import Source
from fn.web.app import create_app
with mock.patch("fn.config.keychain", return_value=None):
    s = config.from_env()
app = create_app(s, None)
with TestClient(app, base_url="http://127.0.0.1") as c:
    app.state.store.upsert_source(Source(id="src-x", kind="page", url="https://example.org/x", text="Made-up text.", content_hash="h-x"))
    print(s.stored_record, "Show the stored record" in c.get("/sources/src-x").text)
EOF
done
```

Expect `False False`, then `True True`.

## Not doing

- Showing the stored text on the debug source page or anywhere else. With the setting off it is on no page; the debug page links to the source page.
- A change to `fn.css`: the `fn-source__stored` rules stay for when the setting is on.
- A change to the design system files outside the repository; the lead updates those.
- A change to how the passage is cut or where `#quote` sits.
