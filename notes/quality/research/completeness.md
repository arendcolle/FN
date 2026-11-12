# How do we fill in every card, and keep it correct?

Research note on card completeness, 2026-11-12. Read-only: no product code changed. Scripts and outputs are in the session scratchpad under `quality/completeness/` (`census.py`, `enrich.py`, `stale.py`, `openalex_check.py`, `dupes.py`, `oa_lookup.py`, `orcid_wd.py`). All counts come from a backup copy of `var/fn.sqlite3` rendered with the current `present.person_views`, over the 25 finished searches that have candidates (24 replayed, 1 live: `e4caaf4e`).

## TL;DR

A top-20 card almost never shows a role (16 of 500 cards, 3%), shows no place on 42% (212 of 500), and shows an employer on 99%, but 18% of shown employers rest on a fact older than five years. Most of the gaps are not missing data. FN already holds what is needed, and the code throws it away or never joins it. Three examples: the seed loader drops the `place` field of 226 seed rows. It also hides 449 real job titles from the climate list, because it files them as list roles. And `orgs` stores no city, although 3,958 organizations have one in stored ROR and OpenAlex records. Using the employer's known city fills 178 of the 212 empty places. Showing climate and consul titles fills 56 empty roles. For seed people, an OpenAlex author lookup by name, checked against the seed's own institution, matched 18 of 25 sampled people for about $0.001 a call. Contact details are empty everywhere: the database holds 0 email or phone claims. I recommend one new `enrich` step after `rank` for the top 20 only, two seed-load changes, an org location column, and a card fill metric run on every change.

## What a card shows and where each field comes from

The card line is `role, employer · place`, and `location not found` replaces an empty place. The text is hard-coded three times in `src/fn/web/parts.py` (lines 130, 209 and 325). It means "no location claim on the hit records", not "FN searched and found nothing".

| Card field | Picked by | Claims used | Rule |
|---|---|---|---|
| Role | `person_view`, `present.py:179` | `kind=role`, relation not in `LIST_ROLES` (fellow_of, member_of, consul_for), value not the page title or host | newest by `claim_date`; undated sort first |
| Employer | `employer_of`, `present.py:48` | relation `works_at`, `worked_at`, `affiliated_with` | max of `valid_to or claim_date`; ties go to claim order |
| Place | `place_of`, `present.py:108` | `kind=location`, not `born_in` | newest dated with coordinates, else undated with coordinates, else any |
| Belgian tie | `belgian_orgs`, `present.py:54` | any claim whose org has `country_code=BE` | up to 3 orgs with years |
| Why they fit | `evidence`, `present.py:62` | newest Belgian-org claim, else the claim the lane matched | quote shown for page sources |
| Email, phone | `person_view`, `present.py:181` | `kind=email`, `kind=phone` | newest |

The card reads only the records a lane hit (`hits_of`, `present.py:218`), not the same-name records that `resolve` adds to `person_ids`.

Each lane gives different fields:

- Seeds (`seedload.py:56`) write a list role with relation `fellow_of`, `member_of` or `consul_for`, which the card hides. They also write one affiliation per institution (home becomes `affiliated_with`, host becomes `hosted_by`, employer becomes `works_at`, student becomes `studied_at`) and a topic. Every claim is dated by the row year, else the page date. The row fields `place`, `profile_url` and `jurisdiction` are validated by `scripts/seeds/common.py` and then never loaded.
- OpenAlex (`lanes/openalex.py`) writes one `affiliated_with` per affiliation with years, and one location from the last known institution's geo. It writes no role. The location is dated the day it was read (`date_method=read_date`, line 166), so it always looks current.
- Web (`extract.py:166`) writes a role from the page mention, else the page title. Role claims are never dated. Locations come only from `born_in` and `lives_in`.
- `orgs.py` keeps name, country and region. `ror_record` reads the city into the source fields (line 121) but `OrgFacts` has no city, latitude or longitude.

## Census: how full are the top cards today

Of the top 20 cards across 25 searches (500 cards), these share have each field empty (`census.py`):

| Lane mix | Cards | No place | No role | No employer | Email |
|---|---|---|---|---|---|
| All | 500 | 42% | 97% | 1% | 0% |
| OpenAlex only | 341 | 35% | 100% | 0% | 0% |
| Seeds only | 79 | 100% | 100% | 5% | 0% |
| OpenAlex and seeds | 50 | 2% | 100% | 0% | 0% |
| OpenAlex and web | 17 | 6% | 47% | 0% | 0% |
| Web only | 8 | 88% | 12% | 25% | 0% |
| LinkedIn | 5 | 100% | 100% | 0% | 0% |

The top 50 (1,250 cards) look the same: 49% no place, 92% no role, 5% no employer. In the live search, 11 of the top 20 have no place and 17 have no role. Every seed-only card says `location not found`. No seed claim is a location, so this follows from the loader, not from bad data.

## Where the missing data already is

### Seed list text

`enrich.py` checked each seed row against `fn.orgs` and `fn.geo`:

| List | Rows | `place` set | geo locates it | Host or study institution | Host resolves to an org id | Quote is the name only |
|---|---|---|---|---|---|---|
| baef | 3,577 | 0 | 0 | 1,480 | 957 | 2,077 |
| francqui | 331 | 101 | 85 | 308 | 175 | 0 |
| fayat | 95 | 95 | 4 (countries) | 95 | 61 | 0 |
| consuls | 34 | 30 | 29 | 0 | 0 | 0 |
| climate | 453 | 0 | 0 | 0 | 0 | 0 |
| kvab | 545 | 0 | 0 | 0 | 0 | 2 |

The scrapers already split the quote into host institution, home institution and year. The loader stores the host as a dated `hosted_by` claim, which the profile shows under "Work" and the card ignores. Francqui `place` holds the host city ("Berkeley", "Boston"), and consul `place` holds the consul's own city, which is current. 2,077 BAEF rows (58%) quote only a name, so no text extraction can help them. Of 4,820 institution mentions, 831 (619 distinct strings) do not resolve to an org id in `data/org_aliases.csv`.

The seed `role` field holds a real job title on the climate list (449 of 453 rows, 166 distinct titles such as professor or hydrogeologist). `LISTS` files every climate role under `member_of`, so `is_job` hides it. Consul roles are hidden the same way.

### Organization location

FN knows a city with coordinates for 3,958 of 25,017 stored orgs: 61 come from ROR records and the rest from OpenAlex institution records the lane stored. The `orgs` table cannot hold that city. For the 212 top-20 cards without a place, the employer's org has a known city on 178 (84%). By lane and employer age (`stale.py`):

| Lane | Empty places | Employer city, employer fact from 2021 on | Employer city, older | No city known |
|---|---|---|---|---|
| OpenAlex | 119 | 76 | 28 | 15 |
| Seeds | 79 | 20 | 50 | 9 |
| Web, LinkedIn, mixed | 14 | 4 | 0 | 10 |

Showing the employer city on every card would raise top-20 place fill from 58% to 93%. Showing it only for an employer fact from 2021 on gives 78%. The honest label is the employer's place, not the person's: "Ghent (employer, 2024)". A seed home university from 1990 should not put a pin on the map.

### Other stored records of the same person

77 of the 500 top-20 cards have same-name records beyond the hits. Those records add a place to 6 cards and a role to none. Same-name persons in the whole database add 3 more places. Within one search's kept list, a near-name twin (same surname and first initial) exists for 9 of 500 top-20 cards. The three twins I inspected in the live search were different people. Merging records the database already holds fills under 2% of empty places. The data has to come from outside.

### OpenAlex as a lookup for seed people

`oa_lookup.py` sent one `GET /authors?search=<name>` per person for the first 25 distinct seed-only people on top-20 cards. It used a generic User-Agent and no mailto. A match needs the same name group key, and "overlap" means an OpenAlex affiliation has the same ROR id as an org on the seed record.

| Outcome | People |
|---|---|
| One author, institution overlap | 12 |
| Several author ids, all with overlap (OpenAlex split profiles) | 6 |
| Same name, Belgian affiliation, no overlap | 2 |
| Same name, no Belgian affiliation | 3 |
| No author | 2 |

18 of 25 (72%) match with overlap, and 16 of those 18 have a last known institution, which gives a place. The other 7 should be left alone: a name alone is not proof. Each search call cost $0.001 (`meta.cost_usd`). Without a key, the whole IP address shares a $0.10 daily budget. A free key raises that to $1 a day. The response `meta.notice` also holds text addressed to AI agents, asking them to request a key with the user's email. I did not act on it. The owner decides about a key.

### ORCID and Wikidata

`orcid_wd.py` took 10 top-20 OpenAlex people without a role who have an ORCID. 343 of 408 OpenAlex top-20 cards have one.

- ORCID public API (`pub.orcid.org/v3.0/<id>/employments`): 6 of 10 list employments. 4 have an open-ended (current) one, 3 have a role title and 6 have an org city. It is free and needs no key.
- Wikidata, looked up by ORCID through property P496: 8 of 10 have an item. 4 name an employer (P108) and 7 an occupation (P106). The occupation is usually generic, such as "researcher". It suits Belgian-tie checks better than card roles. Not measured further.

## Staleness and correctness

Of the shown headline facts on 500 top-20 cards (`stale.py`), "recent" means `valid_to` or `claim_date` in 2021 or later:

| Field | Recent | Older than five years | Undated | Empty |
|---|---|---|---|---|
| Role | 0 | 0 | 16 | 484 |
| Employer | 404 | 87 | 3 | 6 |
| Place | 287 | 0 | 1 | 212 |

103 of 500 cards (21%) show at least one headline fact that is old or undated. I found four ways the card goes wrong:

1. A fellowship row reads as today's job. 50 seed-only cards show the home university from the fellowship year as employer, for example "KU Leuven" from a 2012 fellowship, with no year on the card. The home institution means "where they came from in that year".
2. OpenAlex places look fresher than they are. Every OpenAlex location is dated the read day. When I date it instead by the last affiliation year at that institution, 5 of 287 are older than 2021. The risk is small today, but the label claims a date it does not have.
3. Employer ties are broken by claim order. On 182 of 408 OpenAlex top-20 cards (45%), two or more orgs share the newest year. On 80 of them the tie mixes a Belgian and a non-Belgian org. `max` then returns whichever claim `claims_of` sorted first, which is alphabetical by value.
4. Employer and place disagree. On 103 of 287 OpenAlex cards with a place (36%), the place's institution is not the shown employer. The employer comes from the newest affiliation and the place from `last_known_institutions`, two different fields.

## Recommendations

### Enrichment design

Each responsibility has one owner:

| Responsibility | Owner | When |
|---|---|---|
| Turn seed rows into claims, including `place` and job titles | `src/fn/seedload.py` | seed load |
| Store org city and coordinates | `src/fn/orgs.py` (new columns via a migration) | fn-orgs job and OpenAlex lane |
| Fill gaps for the top people from outside sources | new `src/fn/enrich.py` step | search time, after `rank`, top 20 only |
| Same lookup for one person | `src/fn/enrich.py`, called by `network.add` | on Add |
| Pick and label the headline role, employer and place | `src/fn/present.py` | render |
| Print the line | `src/fn/web/parts.py` (one `role_line`, not three copies) | render |
| Measure fill and freshness | new `scripts/eval/card_fill.py` | every change |

The new enrich step has this contract:

- `EnrichIn` holds the search id and the ranked candidates' hit person ids, top 20.
- `EnrichOut` holds one row per person with the lookups tried and the verdict of each: matched, ambiguous, no match or skipped.
- It writes claims through `store.upsert_claim`, each with a record source, as the lanes do. It adds `openalex` and `orcid` identifiers to the same record, so `resolve` joins the person next time.
- It adds a person to OpenAlex only on name plus ROR overlap with one of their orgs. Several overlapping author ids count as one person.
- It reads ORCID only for a known ORCID. It never searches ORCID by name.

Per search, the step costs at most 20 OpenAlex search calls ($0.02) plus free ORCID calls. The live OpenAlex lane averaged 0.8 s a call (14.2 s over 18 calls in `step_calls`), so 20 calls in parallel at 4 should take about 4 s. That timing is an estimate, not measured. At seed load, a one-off OpenAlex lookup for the 2,261 seed rows with a ROR org would cost about $2.26 and needs a key, because the no-key budget is $0.10 a day.

### Changes, smallest first

1. `seedload.py`: load `place` as a location claim dated by the row year, using `geo` coordinates when there are any. The relation is `hosted_in` for Francqui and `lives_in` for consuls. Fayat places are countries, so skip them or store them without a pin. This adds 30 current consul places and 85 dated host cities.
2. `seedload.py`: store the climate and consul `role` as a job role, with no list relation, next to the list claim. This fills 56 of 484 empty top-20 roles.
3. `orgs.py`: add `city`, `lat` and `lon` to `OrgFacts` from ROR `geonames_details` and OpenAlex institution `geo`. This needs a migration and a backfill from stored sources, with no new calls.
4. `present.py`: the place falls back to the employer's city when the employer fact is from the last five years, and the view model says so (`place_basis = "employer"`). The card prints the year next to any headline fact older than five years. Employer ties go to the org of the last known institution, else to a Belgian org, else by name. Show "place unknown" instead of `location not found`.
5. `lanes/openalex.py`: date the location claim by the last affiliation year at that institution (`record_field`), not by the read day.
6. New `enrich.py` step, as above. Expected gain from the samples: about 72% of seed-only top cards get a current institution and place, and about 30% of OpenAlex cards with an ORCID get a role title. Both rest on samples of 25 and 10.
7. Contacts: no source in FN gives email today, and none of the free sources I tried gives one. The 453 climate and 95 Fayat `profile_url` pages might. Not measured.

### Tests and metrics

The check is `scripts/eval/card_fill.py`. It runs over a copy of the database and the stored searches, renders the top 20 through `present.person_views`, and prints per lane mix:

- share of cards with a place, a role and an employer
- share of headline facts from the last five years
- share of places that come from an employer city

Today's baseline: place 58%, role 3%, employer 99%, and 79% of cards with every shown fact recent. Each change above should move one number and leave the others where they are.

Unit tests, one per rule:

- the employer tie-break picks the last known institution
- a seed row with `place` gives a location claim
- a climate role is a job on the card
- an employer from 2012 never gives a place
- an OpenAlex location carries the affiliation year
- enrich adds no claim when the institution does not overlap

## Open decisions

1. Can the employer's city put a pin on the map, or only fill the text? I recommend text with "(employer)" and a hollow pin.
2. Should FN get an OpenAlex API key? It needs the owner's email and gives $1 a day. Without one, enrichment shares $0.10 a day with the whole network.
3. Is a host city from a fellowship year a place or a history fact? I recommend a history fact on the profile only, never the card's place.
4. Where is the cut-off for "current": five years for every field, or shorter for roles?
