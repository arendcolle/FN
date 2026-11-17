# Task s1: the web research lane reads its leads only

## Goal

The scout lane keeps only the leads on a page, but the page reader writes about every person first. On the Washington search one extract call wrote 23,157 output tokens in 82.8 s about a page whose 19 other people the lane then dropped; on the midterms search the same happened with 50 people (`diag-speed.md`). Calls about one or two people took 7.6 to 10.3 s. This task adds a task `extract_leads` that the scout lane uses with the lead names in the user turn. The `extract` prompt stays byte for byte (S6), and `focus` stays as the guard. Expected, as a judgement: the lane's extract phase drops from about 83 s to 10 to 15 s.

## What to build

### `src/fn/prompts/extract_leads.md` (new), word for word

```
Report only the people a researcher asked about. Their names arrive in a <leads> block, one per line, in the spelling the researcher used. Report a person only when the name the text writes matches one of the leads: the text may write a lead with initials for the first names, without a middle name, or with the same words in another order. Report nobody else, even though the rules above say to list every person the text names. For each lead you report, give name as the text writes it and follow every other rule above. When the text names none of the leads, return an empty list.
```

The file holds this one paragraph and a closing newline, and nothing from `extract.md`.

### `src/fn/llm.py`

- `BASES = {"extract_leads": "extract"}`: a task whose prompt is its base task's prompt followed by its own file.
- `system_prompt(task)` (line 50): for a task in `BASES` return `f"{system_prompt(BASES[task])}\n{own}"`, else `own`, where `own` is `PROMPTS / f"{task}.md"`. `extract.md` ends with a newline, so a blank line separates the parts. Both `structured` methods (lines 97, 161) call it, so the hash covers the whole text.
- `TIMEOUTS` (line 22) gains `"extract_leads": 120`, the `extract` value.

### `src/fn/extract.py`

- `LEADS_TASK = "extract_leads"` next to `TASK`.
- `leads_block(names: list[str]) -> str`: each name with its white space collapsed to single spaces, empty names left out, duplicates left out in first-seen order, joined by `"\n"`.
- `read_all(ctx, sources, leads: list[list[str]] | None = None)` (line 142): `leads[i]` names the leads of `sources[i]`. Raises `ValueError` when `leads` is given and its length differs from `sources`. Each chunk of a page with a non-empty `leads_block` is asked with `ctx.llm.structured(LEADS_TASK, {"page": chunk, "leads": block}, PagePeople)`; every other chunk with `TASK` and `{"page": chunk}` exactly as today. Checking, error rows, the warning text and the order stay as they are. `mentions` (line 174) is unchanged.

### `src/fn/lanes/web.py`

- `people(..., focus=None, leads: list[list[str]] | None = None)` (line 58) passes `leads` to `extract.read_all` (line 68), aligned with `pages`. `collect` (line 129) passes none, so the web lane keeps the `extract` task.

### `src/fn/lanes/scout.py`

- Line 111 becomes `web.people(ctx, stored, considered, name, focus=focus, leads=[[lead.name for lead in givers[scout.page_key(s.url)]] for _, s in stored])`, the same names `windows` gets at line 89. `focus` and `same_person` are unchanged.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Building a task's system prompt from its prompt files | `llm.system_prompt` with `BASES` |
| The words of the leads-only rule | `prompts/extract_leads.md` |
| Which task reads a chunk and what the leads block holds | `extract.read_all`, `extract.leads_block` |
| Which leads a page is read for | `lanes/scout.py` (`givers`) |
| Passing a lane's leads to the reader | `lanes/web.people` |
| Whether a reported person is kept as a lead | `lanes/scout.py` (`focus`, `same_person`) |

## Inputs a real run will meet

A page given by one lead; a list page given by several leads (all in the block, in lead order); the same name from two leads (one line); a name with a double space or a newline (one line); an empty lead list for a page (read with `extract`); a lead name holding `</leads>` (a `TagError` chunk row, the other pages read); a 12,000-character window cut into several chunks (each chunk carries the block); a non-lead the model reports anyway (dropped by `focus`, existing test); a lead written as an initial (kept, existing test); a lead without the middle name or in reverse order (dropped by `same_person`, as today); a replay of a search recorded before this task (S6 below).

## Tests (each must fail without the change)

- `tests/test_llm.py`: the sha256 of `system_prompt("extract")` is `234ac9382efa7870f769339942387530d0d908c63c657b2b704c8e4b5962c988`, and `prompt_sha(system_prompt("extract"), user_turn({"page": "Jan Peeters is head chef at Cafe Test."}), schema_json(PagePeople), MODEL)` is `84a727541350ba51ab8d7b6e40a37c8e90b4b9e6c6f059cefff6287ee501f46c` (both measured on main). This one is the guard the brief asks for: it passes before the change and fails if the change touches the `extract` prompt.
- `tests/test_llm.py`: `system_prompt("extract_leads")` equals `system_prompt("extract") + "\n" + ` the text of `extract_leads.md`, and `extract_leads.md` does not hold the first line of `extract.md`.
- `tests/test_extract.py`, with a stub that records `(task, data)`: `read_all` with leads `[["Jan Peeters", "Eva  Maes", "Jan Peeters", ""]]` on a 7,000-character page makes two `extract_leads` calls, each with `leads` `"Jan Peeters\nEva Maes"` and the chunk as `page`; without `leads`, and for a page whose list is empty, the calls are `extract` with `page` only; a lead `"Ann </leads> Example"` gives a `TagError` chunk row while the next page is read; leads of the wrong length raise `ValueError`.
- `tests/test_scout_lane.py`: `ResearchLLM` also records `(task, data)`. Two leads naming one shared page give one `extract_leads` call whose `leads` is `"Jan Peeters\nEva Maes"`, and the lane makes no `extract` call.

## Existing tests that change, approved by the lead

- `tests/test_llm.py` `test_each_task_waits_for_its_own_timeout_and_the_message_names_it`: the `TIMEOUTS` assertion goes from `{"extract": 120, "scout": 420}` to `{"extract": 120, "extract_leads": 120, "scout": 420}`.
- `ResearchLLM` in `tests/test_scout_lane.py` gains a record of the data; no existing assertion changes. It answers by `data["page"]`, which both tasks send, so every scout lane test keeps its kept hits (the brief's first "Done when").

No other existing test may change; stop and report a failure.

## S6: recorded answers and replays

The `extract` prompt does not change, so every recorded web lane page and `tests/fixtures/llm` (30 parse fixtures, no extract) stay valid. A scout page is now keyed `extract_leads-<sha16>`. A replay of a search recorded before this task finds the angles but no page reading: its scout chunks become `FixtureMissing` rows, the lane keeps no hits, and `fn-score run --mode replay` lists that search as degraded. `fn-score` rerank and rescore make no lane call and are unaffected. The lead re-records the panel searches live after merge; the implementer makes no live call.

## Hand check

```
uv run python -m unittest
uv run python -c "from fn import llm; print(llm.system_prompt('extract_leads')[-900:])"
S=$(mktemp -d); FN_VAR=/Users/arend/Developer/FN/var uv run fn-score snapshot $S/snap
uv run fn-score run $S/snap --mode replay --out $S/out --allow-degraded
```

Run the last two on main and on the branch (each from its own worktree). Expected: the branch adds to `meta.degraded` only searches whose scout lane read pages, and the web lane's kept hits are equal.

## Not doing

- A change to the `extract` prompt or the web lane's task. A looser `same_person`. A replay fallback to old `extract` recordings. Contact details, deaths. Running angles on to their pages (research 2b) or a lower scout timeout.
