# Task UI-6a: the design system, version 12

## Goal

Three agents walked the rebuilt person and source pages ([research/ux2-walk-new.md](../research/ux2-walk-new.md), [research/ux2-walk-check.md](../research/ux2-walk-check.md), [research/ux2-design-review.md](../research/ux2-design-review.md)). The layout holds; the content does not. Work opens with one-year affiliations, page titles stand as jobs, years come from the day a record was read, the summary calls a Walloon tie Flemish, and the debris filter hides about half of the web quotes. The lead ruled V1 to V12 in [design.md](../design.md), "Rulings after the second walkthrough", each a rule of the design system first. This task writes those rules into the design system so a site builder can copy them word for word. It ships no site code. UI-6b copies the result into the site.

## Where you work

Only the design system's working copy, called `ds/` below; the lead gives you its folder. Files: `ds/project/components/<Part>/README.md` and `preview.html` for Profile, Claim, SummaryList, Quote and SourceText, `ds/project/components/bundle.css`, `ds/project/design-system.json` (`lastChange`), `ds/STRINGS.md`, `ds/DESIGN-NOTES.md`, and two new mockups `ds/preview/page-person-v12.html` and `ds/preview/page-source-v12.html` (copy the v11 files first; leave the v11 files as they are). Read `ds/project/README.md` and the five part READMEs whole before you start. No new token, no new part, no font rule outside the `text-*` classes, every padding in `space-*`.

## Claim (README, STRINGS "Person")

1. Replace the relation list with the complete one, each with one example line, in this order:
   - "Works at" a current job: "Works at Fictional Robotics, 2019–2026"
   - "Worked at" a past job: "Worked at Example Health, 2012–2016"
   - "Studied at": "Studied at KU Leuven, 2008–2013"
   - "Fellow of": "Fellow of Belgian American Educational Foundation, 2015"
   - "Member of": "Member of Koninklijke Vlaamse Academie van België voor Wetenschappen en Kunsten, 2021"
   - "Honorary consul for": "Honorary consul for Belgium"
   - "Hosted by": "Hosted by Massachusetts Institute of Technology, 2015"
   - "Named at", for an affiliation a record or a list gives without a job: "Named at Chalmers University of Technology, 2009–2026"
   - "Lives in": "Lives in Boston, MA"
   - "Born in": "Born in Namur, Belgium"
   - "Origin:": "Origin: Belgian"
   - "Topic:": "Topic: AI in health care"
   - "Paper:" with the title and its year, as today: "Paper: Deep learning for sepsis alerts, 2023"
2. Remove "Affiliated with", "Based in" and "Field:" from the README and STRINGS. A place a record gives for an institution, not for the person, is no fact on the page.
3. A role a source states joins its organization when one source gives both: "`{Role}`, `{organization}`, `{years}`", such as "Head of gynecology, UZ Leuven, 2014–2026". The role starts with a capital letter. A role whose organization comes from another source stands alone: "Chief scientist, 2024".
4. A list entry reads as its relation and the list's organization, never as the list's title: "Fellow of Belgian American Educational Foundation, 2015", not "BAEF Belgian Fellows, 2015".
5. A page's title is no fact. When a page names a person without a role, the title never shows as a line, a role line or a sentence; the page shows under Sources only.
6. Years: the line shows the fact's own years as one span, first to last ("2009–2026"), or one year ("2015"). A fact's own years are the years its source states for it. The day a record was changed or read is never shown as a fact's year. When the years have gaps, the proof adds, before the cite, `<p class="fn-cite text-small">Years: 2009, 2011–2012, 2019, 2021–2026</p>`.

## Profile (README)

7. Work order, word for word: "Work opens with the current job: of the jobs a source states as current or whose years reach the last two years, the one with the longest span, with the role a source states for it. Then the other roles pages and lists state, then the other facts at Belgian organizations, then the rest, longest span first. Affiliations a record lists for one year only fold into one last line."
8. The head's role line is the first Work line when it is a job (the current job or a stated role): its role and organization, then " · " and the place. A topic, a paper, a past job or a list entry never names the head. With no such line, the role line is left out.
9. The folded line, last in Work, with no Not correct: `<div class="fn-claim" id="work-fold"><div class="fn-claim__head"><div class="fn-claim__line"><span class="fn-claim__what text-body">Also named at 30 other organizations</span> <details class="fn-proof"><summary class="fn-proof__name text-small" aria-label="Source for Also named at 30 other organizations: OpenAlex record">OpenAlex record</summary><div class="fn-proof__body"><p class="fn-cite text-small">University of Pisa, 2019 · Stony Brook University, 2021 · …</p></div></details></div></div></div>`. It counts as one line for "Show `{n}` more". One-year affiliations at a Belgian organization never fold.
10. "Ties to Flanders and Belgium" holds ties only: a birthplace in Belgium, a Belgian origin, a fellowship, a membership and a consul's post from a Belgian list or at a Belgian organization. A job is under Work, a degree under Education, a topic under Work as "Topic:", any other place under Places.
11. Sources: one row per record, as many rows as "Combined from `{n}` records" says. A row is named by where the record came from: a page by its host ("columbia.edu"), a list by its name ("BAEF Belgian Fellows"), a record by its kind ("OpenAlex record", "LinkedIn record"). Two rows with one name each add ", `{organization of that record's first Work line}`". Then "· `{n}` facts", or "· no facts" for a page that only names the person. "Not this person" shows on every record but the page's own, which comes first. With one record the section is left out, unless the page has no fact line: then its one row shows.
12. Same person, Different person, their Undo and the back link from a possible match return to `#matches`; Not this person and its Undo return to `#sources`.
13. The first-screen budget of 90 words counts the head, the why block and the summary, not the facts and not the forms.

## SummaryList (README, STRINGS)

14. The tie row is the strongest tie: with a search the tie the ranker stored, else the one the tie evidence picks, and only a strong or medium one. Its key is "Tie to Flanders" when the tie's organization or place lies in Flanders and "Tie to Belgium" otherwise, Brussels and an unknown region included. Its value is the tie in Claim words.
15. When the tie is the Studied row's fact, the Studied row is left out, so the summary never says one fact twice.

## Quote (README), word for word

16. "A quote is left out only when it is page furniture: it starts with a field label after a list mark (“* Name:”), holds image or author-list tokens (“Author Orcid Image”), holds a markup entity (“&amp;nbsp;”), or has fewer than four words. A sentence that names the person as “she” or “he” stays."
17. A LinkedIn profile is a record, not a page: no quote, no passage, cite "LinkedIn record".

## SourceText (README, STRINGS "Source", bundle.css)

18. Under the sentence, the cite line names the source: `<p class="fn-source__cite text-small">{source label}, {date}</p>`, the label and date of the proof's cite, the date left out when unknown: "BAEF Belgian Fellows, 2015", "columbia.edu, May 2024", "OpenAlex record, 2025".
19. For a page that only names the person, the sentence reads "The page names `{name}`."
20. `bundle.css`: add `overflow-wrap: anywhere;` to `.fn-source__passage` and `.fn-source__lead`, so a long word or address never widens the page at 390 px. Add `.fn-source__cite { margin: calc(-1 * var(--space-3)) 0 var(--space-4); color: var(--muted); max-width: var(--measure); overflow-wrap: anywhere; }`, so it sits `space-1` under the lead.

## Previews and mockups

Made-up people only, none of them real. Each state has its `<p class="cap text-small">` caption; check every preview at 390 px and 1280 px.

- Claim preview: a joined role, a list entry, "Named at", "Topic:", a proof with the "Years:" line.
- Profile preview: Jonas Testman, a web person named on one page without a role (no role line, no Work, Sources with one row "· no facts"); Mira Proef, a fellow whose tie is the fellowship (Ties holds "Fellow of Belgian American Educational Foundation, 2015", summary "Tie to Belgium"); Sources of a combined page with two "OpenAlex record" rows told apart.
- SummaryList preview: Luc Exemple, tie at UCLouvain, key "Tie to Belgium"; a degree at KU Leuven that is the tie, so no Studied row and "Tie to Flanders: Studied at KU Leuven".
- Quote preview: a "she" sentence that shows; "* Name: Mira Proef" left out.
- `page-person-v12.html`: Elke Voorbeeld, a researcher. Head "Professor, Chalmers University of Technology · Gothenburg, Sweden". Work: "Professor, Chalmers University of Technology, 2009–2026", "Named at Ghent University, 2003–2008", "Named at IMEC, 2005", then Show more; expanded (a second state in the file), "Named at Massachusetts Institute of Technology, 2006–2012" and the folded line "Also named at 30 other organizations".
- `page-source-v12.html`: Jonas Testman's page: "The page names Jonas Testman.", the cite line, and a passage with a 60-character email address that wraps at 390 px.

## DESIGN-NOTES and version

One entry per changed part (Claim, Profile, SummaryList, Quote, SourceText): the ruling (V1 to V12), the pattern followed, and what it leaves out. Add a "Pages, round 12" line for each new mockup. Set `design-system.json` `lastChange` to a version 12 note naming V1 to V12.

## Done check

Open every changed preview and both mockups headless at 390 px and 1280 px: no horizontal scroll, each state as written. `grep -c "fn-source__cite\|overflow-wrap: anywhere" ds/project/components/bundle.css` grows by at least 3 over version 11. `grep -n "Affiliated with\|Based in\|Field:" ds/STRINGS.md ds/project/components/*/README.md` prints nothing. Report the new sha256 of `bundle.css` (`shasum -a 256`); UI-6b pins it.

## Not doing

- Site code, `src/fn/web/static/fn.css`, tests.
- The card's reason and second line, the why block and the map (UI-4 has them; their strings stay).
- "Not correct" on hover only (review 12): V12 takes forms out of the budget instead.
- Regenerating `ds/site-fn.css` or the v11 mockups.
