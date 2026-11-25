# Task K2: a job at a Belgian company, medium or agency counts as a tie

## Goal

A job is a tie only through an org id with country BE (`orgs.py:92`). 314 `works_at`/`worked_at` claims at 118 Belgian employers have none, and 114 of their 261 people have no tie. The Flemish broadcaster's US correspondent (person `4c190bc6`) stands under "Topic, no known tie" because "VRT NWS" has no id. Brief K2: checked alias rows, stored claims linked from the file before ROR, and posts abroad that give a tie and no place.

## What to build

Commit 1 code and tests, commit 2 data.

### `src/fn/orgs.py`

- `_rows` (line 48) returns `(alias, org_id, post: bool)` from column `post`: empty or missing is False, `yes` True, else `ValueError(f"org_aliases.csv: post {mark!r} for {alias!r} is not empty or yes")`. `_by_alias`, `names` and `ids` unpack three fields.
- New, after `ids`:

```python
@cache
def _posts() -> frozenset[tuple[str, str]]:
    return frozenset((fold(alias), org) for alias, org, post in _rows() if post)


def post(text: str, org: str | None) -> bool:
    """Whether the alias file marks this spelling of org as a post away from its home, such as a US arm or a consulate."""
    return (fold(text), org) in _posts()


def overruled(answers: dict[str, str | None]) -> dict[str, str]:
    """Each stored ROR answer for a name the alias file gives another org: the folded name and the answer's org."""
    return {key: org for key, org in answers.items() if org and _by_alias().get(key, org) != org}
```

- `unlinked` (line 276) gains `wrong: dict[str, str]` and also returns claims whose org is `wrong.get(fold(value))`: from `store.linked_affiliations(MATCH_RELATIONS, sorted(set(wrong.values())))` without person_ids (none when `wrong` is empty), in the `claims_of` filter with them.
- `match` (line 291) reads `answers` first and calls `unlinked(..., overruled(answers))`. With `aliases = _by_alias()`, the sort key becomes `(g[0] not in answers and g[0] not in aliases, g[1][2], g[0])`, so file names link before a call can fail. First in the loop: `if key in aliases: linked += ctx.store.relink_claims(claim_ids, aliases[key]); continue`. Such a name is never asked or counted; `org_matches` keeps ROR's answer. The docstring says so.

### `src/fn/store.py`, after `link_claims` (line 438)

- `linked_affiliations(self, relations: tuple[str, ...], org_ids: list[str]) -> list[tuple[str, str, str]]`: id, value and org of each claim with one of the relations and orgs, rejected ones too, by id.
- `relink_claims(self, claim_ids: list[str], org_id: str) -> int`: sets the org `WHERE id IN (json_each) AND org_id IS NOT ?`; returns rows changed.

### `src/fn/evidence.py`

`places` (line 140): the employer test adds `and not orgs.post(c.value, c.org_id)`, and the docstring says a post gives no city. The ranker, the page and the seeds lane all read places here.

### `data/org_aliases.csv`

Header `alias,org_id,post`; existing rows unchanged. Append rows grouped by org: brief decision 1 with the spellings seen (`$S/q6_groups.json`, or rerun `$S/q6e.py` on a copy), plus the six Antwerp academy spellings `org_matches` holds against `ror:02zzhpq74`. `post` is `yes` on US arms, consulates, embassies, FIT, AWEX, WBI and the VRT NWS spellings, each pointing at its parent (embassies and consulates at the foreign ministry). "federal government" alone and "Anheuser-Busch" get no row.

Check each id at ROR, else Wikidata, for name and country BE; keep that table outside the repo and report names with no Belgian record or two. Each new id gets the record `tests.helpers.recorded_orgs` serves: `tests/fixtures/http/ror/<id>.json`, or `wikidata/wbgetentities-<Q>.json` and `wbgetclaims-<Q>-P17.json`. A name that gets a row leaves `data/org_aliases_unmapped.txt`.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Which spelling names which Belgian org, and which is a post | `data/org_aliases.csv` |
| Reading the file and the mark | `orgs._rows`, `orgs.post` |
| Linking stored claims, alias before ROR answers | `orgs.match`, `orgs.overruled`, `orgs.unlinked` |
| Writing claim org ids | `store.link_claims`, `store.relink_claims` |
| Whether an employer's city is a place | `evidence.places` |
| Registry facts per id | `orgs.run` (`fn-orgs`) |

## Recorded answers, replay and stored searches (S6)

No prompt changes; every recorded model answer replays. Alias names skip ROR, so a replayed search may ask one more name under `LINK_MOST`; a miss fails only the link step. Until the match job links a post spelling, a rerank keeps every stored search exactly, version 1 included (hand check 1). After `fn-orgs --match`, newly linked people change in every search holding them.

## Inputs a real run will meet

Other capitals and spaces (tests 1, 4); `&` for "and" (1); empty text (1); an alias plus words (1, 4); a bad or missing `post` cell (2); a non-Belgian record (3); every alias at once (5); a NULL answer (4); a wrong answer, a record's id, the right id (6); a 429 (7); a post spelling at another org (8); a stated place (9).

## Tests (each must fail without the change)

Made-up people only. `tests/test_orgs.py`:

1. `AliasTest.test_a_post_spelling_names_its_parent_and_carries_the_mark`: "VRT NWS", " vrt  news " give VRT's id, marked; "VRT" unmarked; "UCB USA" gives UCB's id; both FIT spellings one id; "VRT NWS Brussels" and "" None.
2. `AliasTest.test_a_post_cell_other_than_empty_or_yes_stops_the_load`: a patched temp `ALIASES`, caches cleared: "maybe" raises, a two-field row reads unmarked.
3. `FnOrgsTest.test_every_post_row_points_at_a_belgian_record`: after `save_recorded_orgs`, at least 10 post rows, all BE, and VRT's id BE.
4. `MatchTest.test_an_alias_name_links_from_the_file_without_a_call`: a NULL answer for "vrt nws"; "VRT NWS", "  vrt nws ", "VRT NWS Brussels" with `most=0`: two links, `left` 1, no call.
5. `MatchTest.test_every_alias_spelling_links_in_one_run`: one claim per file row; `linked` equals the row count, no call.
6. `MatchTest.test_an_alias_overrules_a_stored_answer_and_relinks_only_what_it_linked`: answer "vrt nws" is `ror:00j54wy13`; of "VRT NWS" claims at it, MIT and VRT only the first moves; an INBO claim at it stays; with `person_ids`, another person's stays.
7. `MatchTest.test_alias_names_link_before_a_429_stops_the_asks`: "Aa Lab" 429, job failed, "VRT NWS" claim linked.

`tests/test_evidence.py`, with a made-up VRT `Org` in Brussels:

8. `PlacesTest.test_a_post_spelling_gives_a_tie_and_no_employer_city`: "VRT NWS" in 2026: no place, medium `belgian_org` tie; "VRT" gives Brussels; "VRT NWS" at MIT's id, Cambridge.
9. `WhereTest.test_a_post_employer_leaves_the_place_unknown`: Boston area: "VRT NWS" unknown, "VRT" outside, plus lives in Boston inside.

## Existing tests that change, approved by the lead

None; 1,177 pass today. If one fails, for example because a seed employer now links in the seeded database, stop and report.

## Hand check

`S=<scratch folder>` (if gone, stop and report), `H` a new folder outside the repo, `git -C <repository> worktree add --detach $H/main c6cd0c6`, `VM=$($S/bin/mkvar.sh k2-main)`, `VB=$($S/bin/mkvar.sh k2-branch)`; every run `FN_HTTP=replay FN_LLM=replay`.

1. `FN_VAR=$VM uv run fn-rerank --all` in `$H/main`, `$VB` here: candidate rows identical. Back up `$VB` as `$H/before.sqlite3`.
2. `$H/k2.py` (`PYTHONPATH=.`): `tests.helpers.save_recorded_orgs`, then `orgs.match` with `OrgMatchIn(most=0, pace_s=0)` in a job (no call); grade `evidence.tie` for the people in `$S/q6_gain.json` "before". Expected: at least 100 of its 114 "gain" strong or medium.
3. `fn-rerank --all`; `$H/diff.py` against `$H/before.sqlite3`: correspondent heading 2 to 1, place-fit moves by pair, 0 from unknown to outside or abroad through a post claim.

## Not doing

Suffix rules, fuzzy matching, nationality, tie grades, headings, `belgian_text`, ROR rules for other names, non-Belgian employers. Relinking ids from ORCID or OpenAlex, or rewriting `org_matches`. "federal government" alone keeps its Malaysian answer.
