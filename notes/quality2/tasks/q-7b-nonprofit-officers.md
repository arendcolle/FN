# Task Q-7b: nonprofit officers from the Form 990 filings as a seed list

## Goal

The business people an organizer invites sit in small named lists. The Form 990 officer lists of about 12 Belgian-American nonprofits hold about 100 to 150 people with a role and a fiscal year, and found 2 of the 5 non-researcher gold picks (GS-23#2, GS-32#4) (`research/people-sources.md`). This task adds one seed script that reads the IRS bulk filings the lead downloads, and its loader spec. The builder writes it against saved sample files with made-up names and never calls out. Decision W4 in `design.md`. By the lead's ruling the nonprofit officers come last among the lists, because their filings sit in large bulk files; the two one-page lists (Q-7a) merge before this task. Owner: `scripts/seeds/` and `seedload.py`. Needs nothing in code; Q-3 grades this list medium already (`tasks/q-3-evidence.md`, `STRONG_LISTS`).

## Before the builder starts (the lead)

Save these files with every person's name replaced by a made-up one (Ann Example), keeping the structure. In the XML, also replace every `PhoneNum`, the preparer's name, firm and PTIN, and every street address with made-up values (or drop those elements); keep the EIN and the Part VII groups. The repository is public.

- `tests/fixtures/seeds/irs990/index_2024.csv`: the header line of `https://apps.irs.gov/pub/epostcard/990/xml/2024/index_2024.csv` and six rows: two filings of one EIN of the list below for two tax periods, one 990-EZ of another, one made-up row with `RETURN_TYPE` "990N" (the e-file index lists no 990-N), and two rows of EINs not on the list.
- `tests/fixtures/seeds/irs990/form990.xml` and `form990ez.xml`: one 990 and one 990-EZ filing XML taken from the IRS bulk zip named by the index row's `XML_BATCH_ID`.

## What to build

The script copies the shape of `scripts/seeds/chambers.py`: a reader, `build_rows(...) -> list[dict]` with the row fields `common.REQUIRED` lists (`scripts/seeds/common.py:15`), `main()` that writes through `common.write_rows`. Rows of a person named twice keep the first.

### `data/seeds/irs990-orgs.csv`

Columns `ein,name`, no person's name. Rows with EINs the research probe found on 2026-11-12: 131606002 Belgian American Educational Foundation; 131612163 The Belgian American Chamber of Commerce in the United States; 463513968 Belgian American Chamber of the South; 461274501 Amici Lovaniensis (Leuven alumni, Bay Area); 742202282 Belgian-American Club of Texas; 362123825 Flemish American Club; 382226809 Genealogy Society of Flemish Americans; 800615943 Namur Belgian Heritage Foundation. The lead adds the EINs of Belwest, the Belgian-American club of Chicago and the Flemish-American groups from the index's `TAXPAYER_NAME` before the run.

### `scripts/seeds/irs990.py`, list `irs990`

- The script makes no call: `main(folder)` reads `index_*.csv` and the zips the lead downloaded into `data/seeds/raw/irs990/`.
- `filings(index_csv: str, eins: set[str], year: int) -> list[Filing]`: rows of a listed EIN with `RETURN_TYPE` 990, 990EZ or 990PF, the newest `TAX_PERIOD` per EIN. `Filing(ein, object_id, batch, tax_period, return_type, index_year)`. A listed EIN with no such row prints `no XML filing for {ein} {name}`.
- `officers(xml: bytes) -> tuple[int, list[tuple[str, str]]]`: `xml.etree.ElementTree` in the `http://www.irs.gov/efile` namespace; the `TaxYr`, then `PersonNm` and `TitleTxt` of each `Form990PartVIISectionAGrp`, `OfficerDirectorTrusteeEmplGrp` and `OfficerDirTrstKeyEmplGrp`; a group without `PersonNm` is skipped.
- Row: `name` title-cased when the filing writes it in capitals, `name_on_page` as written, `year` the tax year, `role` the title, institutions the org's name from the CSV as `member_of`, `source_url` `f"https://apps.irs.gov/pub/epostcard/990/xml/{index_year}/{batch}.zip#{object_id}_public.xml"`, `source_title` `f"Form {return_type} of {org}, tax year {year}"`, `source_date` None, `date_method` "none", `row_key` `common.row_key(LIST, name, year, ein)`, `quote` the line `f"{name_on_page}, {title}, {org}, tax year {year}"` of the filing's text layer.

### `src/fn/seedload.py`

`SPECS` (line 42) gains `"irs990": ListSpec(None, job=True)`. A 990 row's year dates its claims as a record field (line 96), so a lagging officer list reads as dated history.

## Inputs a real run will meet

A name in capitals; a filing with a business as officer; the same person in two filings; an EIN with only a 990-N; two tax periods of one EIN; an index row of an EIN not on the list; a group without `PersonNm`.

## Tests (each must fail without the change)

- New `tests/test_seed_irs990.py`: `filings` keeps the newest period per listed EIN and skips the 990-N and the other EINs; `officers` reads both fixtures; a name in capitals is title-cased and keeps `name_on_page`; a loaded row's claims carry the tax year as `claim_date` with `date_method` "record_field".

## Existing tests that change

None. Stop and report a failure.

## Hand check

`uv run python -m unittest` all green. The lead runs `uv run scripts/seeds/irs990.py data/seeds/raw/irs990`, then `uv run fn-seed`; counts rows against the research's 100 to 150; checks that GS-23#2 and GS-32#4 are present as seed records; opens two loaded people's pages.

## Not doing

The BelCham board and the embassy's advisors (Q-7a). ProPublica pages. Alumni boards other than those in a 990. SEC filings. A person's place from the organization's address.
