# Task UI-3: the readable source page

## Goal

A source page opens 724 px down at the highlighted quote, names neither the person nor the fact, shows the site's menus as text, and runs to 1,063 to 17,729 words ([research/ux-walk-walk-check.md](../research/ux-walk-walk-check.md), problem 4; walk-new, problem 3). Staff cannot tell what the highlight should prove. Decision U6 in [design.md](../design.md): a back link, a heading that names the person, one sentence built from the stored fact, the passage in context, a link to the original, and the stored copy behind "Show the stored record". No model call: the sentence is a template over the stored claim.

## Before you start

UI-1 is merged (the back link on this page and the `back` parameter; from a fact it returns to `#claim-{id}` on the person page). Read the design system's `SourceText` and `BackLink` part files and `ds/preview/page-source-v11.html`, and copy their markup. If you need a class or a string the design system does not have, stop and report it.

## Today

`source_page(source, claim)` (`src/fn/web/staff.py:243`) prints the title, the url and the whole stored text in a `pre`, with the quote in `<mark id="quote">`. `get_source` (`staff.py:452`) already loads the claim and refuses a claim of another source. Fact links point at `/sources/{id}?claim={claim_id}#quote` (`src/fn/present.py:206`); Sources rows at `/sources/{id}` without a claim (`present.py:466`).

## What to build

1. `src/fn/present.py` (owner of how a source reads): `source_sentence(claim: Claim, source: Source, org: Org | None) -> str`. For a kind in `present.PROSE`: "The page says: `{fact}`." For every other kind: "The record lists: `{fact}`." `{fact}` is `claim_view(...).what`, then ", `{years}`" when the claim has years. Example: "The record lists: Studied at KU Leuven, 2012–2017."
2. `src/fn/present.py`: `passage(source: Source, claim: Claim, words: int = 60) -> tuple[str, str, str]`: the text before the quote, the quote, and the text after, each side cut to at most `words` words at a word boundary, with "…" where it cuts, white space collapsed to single spaces. A side with no space in its last 400 characters is cut at 400 characters instead. It reads `source.text[claim.quote_start:claim.quote_end]`, which `ClaimDraft` guarantees is the quote (`contracts.py:308`).
3. `src/fn/web/staff.py` `source_page(store, source, claim, back)`, inside `main.fn-source`, in the SourceText order:
   - the back line from UI-1 (`p.fn-back text-meta`);
   - `h1.fn-source__title text-title`: the claim's person, `store.get_persons` of its canonical id, display name; without a claim, `label_of(source)` as today;
   - `p.fn-source__lead text-body`: `source_sentence`, only with a claim;
   - `p.fn-source__passage text-body`: the passage with the quote in `<mark id="quote">`, only with a claim and only for the prose kinds above. A record's lines are never shown as a passage;
   - `<p class="fn-source__url text-small"><a href="{source.url}">Open the original page</a></p>`, left out when the url starts with `fn:` (import and staff sources);
   - `<details class="fn-source__stored"><summary class="text-meta">Show the stored record</summary><pre class="fn-source__text text-body">…</pre></details>`, closed, holding the whole stored text with the quote in a `mark`. That mark carries `id="quote"` only when the page has no passage, so `#quote` scrolls to the passage for a page and opens the short record for a record.
   - `page(...)` gets the person's name as its title when there is a claim, and `current` as UI-1 sets it.
4. `show_source` passes the store. `get_source`'s 404 rules stay.

## Inputs a real run will meet

A 17,729-word PDF text with the quote near the end; a quote at offset 0 and one at the very end of the text; a quote whose surrounding text holds no spaces for 2,000 characters (cut by characters at 400 then, with "…"); a source with no title; a record (`record`, `vendor_record`) whose quote is its raw lines; an import row with an `fn:` url; a staff entry; a source opened without `claim`; a claim of another source (404, as today); a claim whose person was merged since (the merged-into person's name); hostile text in the title, the passage and the url (escaped, and `safe_url` keeps `javascript:` out).

## Tests

In a new file `tests/test_source_page.py`, with made-up names. Each must fail without the change.

- A page source with a claim: the `h1` is the person's name, the sentence reads "The page says: Works at Example Labs, 2019–2024.", the passage holds the quote in `<mark id="quote">` with at most 60 words on each side, and the whole text sits inside a closed `details` whose summary reads "Show the stored record".
- A record source: "The record lists: Studied at KU Leuven, 2012–2017.", no passage, and the stored text's mark has `id="quote"`.
- An import source: no "Open the original page" link; a page source has it as `p.fn-source__url.text-small > a`.
- Without `claim`: the title is the source label and there is no sentence.
- The words shown outside the closed `details` on the 17,729-word fixture (build one from repeated made-up sentences) are at most 200.
- A quote at offset 0 has no leading "…"; one at the end has no trailing "…".

## Existing tests that change, approved

- `tests/test_flows.py`: `walk_browse` (`:398`), whose source page no longer shows "Import contacts.csv" outside the stored record; it asserts the page's `h1` names "Ann Harbor" instead. The fact's link label at `:395` still starts with "Import contacts.csv".

## Existing tests that must stay green unchanged

`tests/test_web.py`: `test_cards_source_and_trace_pages_escape_hostile_text` (hostile text on the source page), `test_card_lists_each_record_with_quote_source_date_and_the_belgian_claims` (its regex reads `<mark id="quote">` followed by the quote text, which the passage or the stored record holds), and `test_the_results_page_names_people_and_shows_no_debug_content` ("content hash" never shows on the staff source page). If one fails, stop and report it. No other existing test may change. Run `uv run python -m unittest`.

## Hand check

Throwaway var folder (`mkvar.sh ui3`), `FN_LLM=replay`, `uv run fn-serve` on your port. Headless Playwright at 1280 px and 390 px: from a person page, open a fact's proof, follow its title link to the source page, screenshot the first screen, open "Show the stored record", screenshot, take the back link. Do the same for a record source and for the longest source in the database (find it with `SELECT id, length(text) FROM sources ORDER BY 2 DESC LIMIT 1`). Count the words on each first screen with `document.body.innerText`. Give the paths and say what you see, without names.

## Not doing

- Cleaning menus or banners out of stored text; the passage window keeps most of them off the first screen.
- Changing how sources are stored or their ids.
- A model-written summary of the source.
- The fact links themselves (UI-2 builds them).
