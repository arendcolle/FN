# Task Q9: a batch that looks up what records miss

## Goal

Every person FN knows only from a seed list has no place, because seed rows hold none, and for 232 of 269 such first-50 cards FN never fetched another record of that person. OpenAlex authors have no role, although 343 of 408 first-20 OpenAlex cards carry an ORCID and ORCID often lists the job title. This task adds `fn-enrich`, an offline batch that fetches those missing records. It never runs inside a search. Decision D13 in [panel-records.md](../panel-records.md); measurements in [research/completeness.md](../research/completeness.md) (the two lookup samples) and [research/identity.md](../research/identity.md).

## What to build

### 1. `src/fn/enrich.py` and the command `fn-enrich`

`fn-enrich [--limit N] [--kind openalex_author|orcid_employment]` runs as a job with one step, like `fn-seed` and `fn-orgs`, because it makes outside calls. It prints the people looked up and the count per verdict. Default limit 200 lookups.

It goes on where it stopped: a table `lookups (person_id, kind, verdict, detail, at)` with one row per person and kind (migration `011_lookups.sql`, store methods to read and write it; the ranking task, built at the same time, takes number 010). A person with a row is not asked again.

Order of work, so a short run helps the most: first people on kept cards of stored searches, best rank first; then everyone else.

### 2. OpenAlex author for a seed person (`openalex_author`)

For a person whose records are all seed rows and who has at least one claim at an organization:

- one call: OpenAlex authors by the person's name (`search=`), the lane's author fields, 10 results
- keep an author only when its name has the seed person's `identity.key` and one of its affiliations is an organization of the seed person's claims (the same org id, of any size)
- store each kept author as its own record, through the same code the OpenAlex lane uses to store an author (give the lane one entry point for it; do not copy that code): person by OpenAlex id and ORCID, affiliation claims, the location of the last known institution, org facts
- then ask `identity.same_person(store, seed_record, author_record)`. Verdict `matched` when it says sure or likely. Verdict `ambiguous` when it says possible: the record stays, as a possible match. Verdict `no_match` when no author is kept. Nothing is copied onto the seed person, and nothing is merged.
- several kept authors are normal: OpenAlex splits one author over several ids

### 3. ORCID employments for an ORCID holder (`orcid_employment`)

For a person record with an ORCID:

- one call to the public ORCID API for that id's employments (no key)
- for each employment without an end date: a role claim with the job title when there is one, and a `works_at` claim at the organization, both dated by the start date as a record field, both quoting a record source "ORCID record <id>" built with `record_source`
- the organization's id comes from the alias file by name, or from a ROR id the employment carries; without either the claim has no org id
- verdict `matched` when at least one claim was written, else `no_match`

### 4. How it runs

Lookups run through `steps.fan_out`, 4 at once, and every store write stays on the step thread. One failed lookup gets the verdict `error` with the reason and does not stop the batch. An `error` row is tried again on the next run.

## Inputs a real run will meet

A seed person with no organization claim (skipped, no row); a name OpenAlex does not know; ten authors with the name, none at the person's organizations; two authors at the same university with the same common name (both kept as records, identity says possible, verdict `ambiguous`); an author record that already exists from a search (no double, verdict by identity); an ORCID with no employments, with only ended ones, with an employment without a title; a 404, a 429 and a timeout; the limit reached mid-batch; a second run (no call for rows already there).

## Tests

With made-up names and recorded answers (the test HTTP stub), in `tests/test_enrich.py`:

- a seed person and one author with the same name and a shared organization: a new record, verdict `matched`, and after `resolve` both records are on one card that shows the author's place
- an author with the name at another organization is not stored: verdict `no_match`
- two authors, common name, shared large organization: verdict `ambiguous`, and the card does not pool them
- an existing author record is reused, not doubled
- an open employment with a title gives a role on the person's view and a `works_at` claim dated by its start; an ended employment gives nothing
- a failed call gives `error`, the batch goes on, and the next run tries it again
- a second run makes no call for people with a row
- the limit stops the batch after N calls
- every store write comes from the step thread

Each new test must be seen failing without the change it covers. Tests that pin the list of applied migrations gain 11: that change is approved. The ranking task adds 10 to the same lists; the manager joins the two at merge. No other existing test may change.

## Hand check

On a throwaway var folder (`mkvar.sh q9`, then `FN_VAR` set to it, live HTTP, no model): `uv run fn-enrich --limit 20 --kind openalex_author` and `uv run fn-enrich --limit 20 --kind orcid_employment`. These 40 calls are allowed: OpenAlex through the app's own client and key, ORCID's free public API. Paste the verdict counts. Then run `uv run fn-rerank --all` on that copy and report, with SQL and no names: how many of the 20 seed people now have a place on their card, and how many of the 20 ORCID holders now show a role.

## Not doing

- A lookup inside a search.
- Reading ORCIDs from Wikidata items.
- Copying an identifier or a fact onto another record, or merging records.
- Searching ORCID or Wikidata by name.
