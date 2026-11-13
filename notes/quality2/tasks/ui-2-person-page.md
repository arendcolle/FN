# Task UI-2: the person page

## Goal

All 54 cards that say "Combined from N records" open a page that shows one record and lists the others as unconfirmed possible matches (blocker in both walkthroughs). Quotes are 60% to 79% of a person page's words, many are page debris ("* company name: …", "… Author Orcid Image"), "Studied at" sits under Work, and two buttons both read "Remove". After a fact is removed the page reloads at the top with the Undo below the fold, and the headline can name a past employer. This task rebuilds the page: head, summary, sections of one-line facts with their proof in place, the combined records of the card, and distinct labels. Decisions U3, U4, U5 and U8 in [design.md](../design.md); [research/ux-patterns.md](../research/ux-patterns.md) has the budget.

## Before you start

UI-1 and Q-1 are merged: the site's `fn.css` is the design system's version 11 bundle (UI-1 copied it; do not copy it again), every link carries its origin, and `origin` is a relation. Read the design system's `Profile`, `SummaryList`, `Claim`, `Quote`, `SectionHeading`, `ShowMore` and `BackLink` part files and `ds/preview/page-person-v11.html`, and copy their markup. If you need a class or a string the design system does not have, stop and report it.

## Markup, from the design system

- Section: `<section class="fn-profile__section" id="{anchor}"><h2 class="fn-section text-title">{title}</h2><div>{claims}</div>{show more}</section>`. Anchors: `work`, `education`, `ties`, `places`, `contact`, `sources`, `matches`.
- Show more, only when a section has more than three facts: `<p class="fn-more text-meta"><a class="fn-link" href="{here with all=work}#work">Show 2 more</a></p>`, where `{here with all=work}` sets `all` with `?` or `&` and replaces any `all` already there, and `{here}` is the page's own path and query (`person_here`), so the link keeps `search`, `shown`, `card` and `back`. No "3 of 5 shown" line.
- Claim: `<div class="fn-claim" id="claim-{id}"><div class="fn-claim__head"><div class="fn-claim__line"><span class="fn-claim__what text-body">{New}Studied at Ghent University, <span class="text-year">2008–2012</span></span> <details class="fn-proof"><summary class="fn-proof__name text-small" aria-label="Source for Studied at Ghent University: ugent.be">ugent.be</summary><div class="fn-proof__body">{quote}<p class="fn-cite text-small"><a href="…">{page title}</a>, May 2024 · <a href="…">Original page</a></p></div></details></div><form …><button class="fn-link text-meta">Not correct</button></form></div></div>`. The what span and `details` sit inline in `fn-claim__line` with one literal space between them. The "Not correct" form is a direct child of `fn-claim__head`, after `fn-claim__line`. `{New}` is `<span class="fn-new text-label">New</span>`. `{quote}` is `<blockquote class="fn-quote text-quote">“…”</blockquote>`.
- Removed fact, in place: `<div class="fn-claim fn-claim--removed" id="claim-{id}"><p class="fn-skipline text-body"><span>{what}, {years}</span><span>· Removed</span><button class="fn-link text-body">Undo</button></p></div>`.
- Summary: `<dl class="fn-summary-list"><div class="fn-summary-list__row"><dt class="text-label">Studied</dt><dd class="text-body">KU Leuven, <span class="text-year">2012–2017</span></dd></div>…</dl>`. Contact not found: `<dd class="fn-contact__none text-body">Not found</dd>`. No source links and no actions in the summary.
- Head: `h1.fn-profile__name text-name`, `p.fn-profile__role text-body`, then `<p class="fn-profile__combined text-small"><a href="#sources">Combined from 2 records</a></p>` when the card combines records.
- Sources rows: `<div class="fn-line"><div class="fn-line__main"><p class="text-body"><a href="…">columbia.edu</a> <span class="fn-line__meta text-meta">· 4 facts</span></p></div>{Not this person form}</div>` inside `div.fn-lines`.
- Possible matches: the section holds `p.fn-note text-small` with `MATCH_NOTE` (`parts.py:323`) and `div.fn-lines`, rows as today.

## What to build

### `src/fn/present.py` (owner of how a fact and a person read)

1. `employer_of` (`present.py:50`) reads only `evidence.EMPLOYER` (`works_at`, `affiliated_with`; `evidence.py:11`), the relations the place already uses. `EMPLOYED` stays for `score.py:102`. A `worked_at` claim is past, so it never names the current employer (lead's ruling). `person_views` calls `employer_of`, so this holds on a card, a network row and the person page alike.
2. Q-1 has already merged: `Relation` has `origin`, `what_of` reads it as "Origin: `{value}`" and `place_of` skips it. Keep both; do not reword it.
3. `source_name(source: Source) -> str`: for a kind in `present.PROSE`, the url's host without a leading `www.`; else `label_of(source)`.
4. `debris(quote: str, name: str) -> bool`, true when any holds: the quote starts with a `key: value` line (optional `*`, `-` or `•`, then 1 to 30 letters, digits or spaces, then `:`); fewer than 6 words remain after removing the words of the name and every number; no word of the name's last part (folded with `fold`) is in it.
5. `proof_quote(claim: Claim, source: Source, name: str, words: list[str]) -> str | None`: None for a kind not in `present.PROSE` (a record's proof has no quote); else `html.unescape` the quote, collapse white space, None when `debris`; else at most 25 words, centred on the first of `words` the quote holds (else from its start), with "…" at a cut end, in the quote marks `quote_words` uses (`present.py:193`).
6. Sections. Each fact stands in one section only (the Profile part). `group_of(claim, facts, source)` returns, in this order: `None` for email and phone; "Education" for `studied_at`, Belgian or not; "Work" for `works_at`, `worked_at`, `affiliated_with` and `hosted_by`, Belgian or not; "Ties to Flanders and Belgium" for `born_in` at a place in Belgium and for `origin` (a birthplace outside Belgium is no tie, so it falls to Places); "Places" for any other location; "Ties to Flanders and Belgium" for `fellow_of`, `member_of` or `consul_for` at a Belgian organization, and for any other claim from a `seed_page` source (a list entry); else "Work". `GROUPS` becomes ("Work", "Education", "Ties to Flanders and Belgium", "Places").
7. `fact_lines` sorts by claim date, then claim id, so a removed fact keeps its line's place (it moved to the end before: walk-new, flow 6). `ClaimView` gains `source: str = ""` and `url: str | None = None`, which `claim_view` fills for every view (`source_name`; the source url, None when it starts with `fn:`). On the person page a line's `quote` text is `proof_quote`, or no quote.
8. `tie_claim(claims, facts, ids: list[str] = ()) -> Claim | None`: the first claim in `ids` that is among the claims; else the newest `studied_at` at a Belgian organization; else the newest claim at a Belgian organization (`orgs.belgian_claims`); else None. UI-4 passes the ranker's tie claims as `ids`.
9. `card_records(store, search_id, person_id, key) -> list[str] | None`: the kept candidate whose `person_id` is `key` and whose `identity.on_card` starts with a record of this person; else the first kept candidate whose card holds a record of this person; its `on_card` records, or None.
10. `profile(store, person_id, today, card: list[str] | None = None, words: list[str] = ())`: with `card`, the claims are `store.claims_of(card)` (all records on the card), `found_as` lists every record on the card and the records merged into them, `possible` leaves out the persons on the card, `records` counts the persons on the card, and `last` is the newest undoable event (`latest`) over every person on the card, so "Not correct" on the second record's fact shows its Removed line with Undo. Without it, the page is as today. New contract fields: `class SummaryRow(Model): key: Literal["Studied", "Tie to Flanders", "Contact"]; value: str; years: str = ""; claim_ids: list[str] = []`; `ProfileView` gains `summary: list[SummaryRow] = []` and `records: int = 1`.
11. The summary: "Studied" is the newest `studied_at` by claim date, its organization name and years (lead's ruling: no claim stores a degree level, so not "the highest degree"); "Tie to Flanders" is `what_of(tie_claim(...))`; "Contact" is "`{email}` · `{phone}`", each a `mailto:` or `tel:` link, the one there is, or "Not found". An empty row is left out, except Contact.

### `src/fn/web/parts.py` and `staff.py`

12. `claim_line`: the Claim markup above. The proof holds the quote when there is one, then the cite: "`{view.label}`" linking to the source page (with `back`, UI-1), ", `{date}`" only when the date is known (never "date unknown"), and " · Original page" linking to `view.url` when there is one. A record's proof is the cite alone ("OpenAlex record, 2025 · Original page"); only an `fn:` url drops "Original page". Keep `id="claim-{id}"` and the `#claim-` next from UI-1.
13. `summary_list(rows)`; `fact_groups` shows `FACT_STEP = 3` facts per section, then the Show more line to `here` with `all={anchor}` set, plus `#{anchor}` (today's `every` keeps `here` the same way, `parts.py:455`). `all={anchor}` shows every fact of that section; `all=1` still shows every section. It leaves out an empty section, a section whose every line's claim ids stand in a summary row, and Places when its only line is the claim `place_of` picks for the head's place. Places no longer reads "Not provided".
14. `profile_state`: the network head's button reads "Remove from network". `found_as_block` becomes the "Sources" section with `id="sources"`, left out with one record as today; "Not this person" shows on a record when it is not the page's person and the not-same route accepts it (merged into this person, or in `network.possible_matches`); the page's own record comes first. `profile_head` adds the combined line when `records > 1`. The card's combined line links to `#sources`.
15. `person_page` (`staff.py:481`): with `search` and `card`, `card_records` gives the card and the words of the candidate's `topic` part detail (split on ", ") give `words`. With `search` and `card`, all four head buttons post to the card's route `/searches/{sid}/people/{key}/{action}` with `next` set to this page's `here`: Add to `add`, Skip to `skip`, Same person to `same` and Add as new to `new`. Same person and Add as new send the same-name network person's id as `match`, the field `card_decision` reads (`staff.py:402`), not the profile form's `other` or `not_same`. So they act on every record on the card as the card does (`card_decision`, `staff.py:400`). `card_action` (`staff.py:426`) then also accepts a `next` of `/people/{id}` with any query, and redirects to that `next` without the `#card-` anchor. Order: back line, head, summary, Work, Education, Ties to Flanders and Belgium, Places, Contact (network people), Sources, Possible matches. Use the card's route only when `card_records` found the candidate; with a `card` the search does not hold, keep the profile routes. With a card, the same-name match comes from the card's records, as `card_decision` checks it.

## Inputs a real run will meet

A seed person with one list role and nothing else; an OpenAlex person with 58 facts; a web person with one page and a debris quote; a person with only a `worked_at` claim; contact present and absent; a `card` key not in the search; a card whose second record was separated since; a removed fact that was the only fact of its section; a quote of 300 words; a quote with `&amp;`; a quote that does not name the person; a person merged into another since the search; a job and a degree at Belgian organizations; a birthplace outside Belgium; a person whose one location is the head's place.

## Tests

In a new file `tests/test_profile_page.py`, with made-up names. Each must fail without the change.

- Section headings are `h2.fn-section.text-title` inside `section.fn-profile__section`, in order, for a person with work, a Belgian degree, a place and an email; a section of 5 facts shows 3 and "Show 2 more" as `p.fn-more > a.fn-link` to `?all=work#work`; a section whose only fact is the Studied row is left out; no "Not provided" for Places.
- One section per fact: a job at a Belgian organization stands under Work only, a Belgian degree under Education only, and a birthplace, an `origin` and a seed list role under Ties to Flanders and Belgium; Places is left out when its one fact is the head's place.
- The summary rows and "Not found"; a person with no degree has no Studied row.
- Opened with `search` and `card`, a card of two unmerged records shows both records' facts, "Combined from 2 records" and "Not this person" on the second; without `search` the second stays under Possible matches. After Not this person the card holds one record.
- Each debris case (`* company name: X`, a name then "1, 2 Author Orcid Image", a sentence without the name) gives no quote but keeps the title link; `&amp;` reads `&`; a 300-word quote gives at most 25 words around the matched word; no "date unknown" in a proof; a record's proof has no `blockquote` and keeps "Original page"; an `fn:` source has no "Original page".
- A claim's what span and `details` are inside `fn-claim__line` with a space between them, and the "Not correct" form is a direct child of `fn-claim__head`.
- The head says "Remove from network", each fact "Not correct", and no button reads "Remove" alone.
- On a page opened with `search` and `card` from a card of two unmerged records, Not correct on the second record's fact shows its Removed line with Undo in place; Add puts both records in the network; for a card whose name matches a network person, Add as new puts both records in the network apart from that person; Show more keeps `search` and `card` in its href.
- A removed fact's line keeps its index in its section.
- A person with only `worked_at` has no employer in the role line on the page, on a card and on a network row; a person with an older and a newer `studied_at` shows the newer in Studied.
- The budget, on five fixture pages (seed, OpenAlex, web, network member, combined), with `<form>` elements and the content of closed `details` left out of every count: at most 90 words in `main` before the first section heading, and at most 180 in `main`.

## Existing tests that change, approved

- `tests/test_person_page.py`: `test_a_network_persons_page_shows_head_contact_and_groups_in_order` (its headings list); `test_each_decision_shows_its_done_line_and_undo_restores_the_page` (the reject case's done text becomes "Field: Tidal energy</span><span>· Removed" and its restored text ">Not correct</button>"); `test_a_long_group_shows_ten_facts_and_all_with_all_1` (3 facts and "Show 37 more" to the page's path with `all={anchor}` and `#{anchor}`, no "of 40 shown" line; `all=1` still shows all 40); `test_a_person_with_two_records_can_separate_one` ("Found as" becomes "Sources"); `test_new_marks_show_once_and_only_a_network_person_moves_seen_at` and `test_a_same_name_candidate_can_join_the_network_person`, the New mark's markup only.
- `tests/test_results_page.py`: `test_the_combined_line_shows_for_two_records_not_merged_into_one`, the anchor only.
- `tests/test_flows.py`: `walk_decide` (`:346`, "Found as" becomes "Sources"); `walk_new_facts` (`:374` and `:379`, the fact's "Remove" becomes "Not correct"); `walk_browse` (`:391`, at least 2 facts, since the head's place leaves Places out).

No other existing test may change. Run `uv run python -m unittest`.

## Hand check

Throwaway var folder (`mkvar.sh ui2`), `FN_LLM=replay`, `uv run fn-rerank --all`, `uv run fn-serve` on your port. Headless Playwright at 1280 px and 390 px: a person from a combined card, a network person, an OpenAlex person; open one proof; press Not correct and screenshot the first screen. Compare each with `ds/preview/page-person-v11.html`. Give the paths and say what you see, without names.

## Not doing

- The why block and the tie and place words from the ranker (UI-4); the source page (UI-3).
- Grading ties on the page; merging records for good; tabs; history replacement after Not correct.
- "+1" when two sources agree.
