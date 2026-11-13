# Better and worse matches: tiers

2026-11-12 · research note for the second quality round · measured on the frozen snapshot `var/score/2026-11-12-final`

## TL;DR

- FN can measure three of the owner's wishes today: topic, tie to Belgium and place. Kind of person, seniority and speaker-readiness have no evidence field. Recency has dates but no rule.
- I replayed `evidence.of` over every stored candidate (27 searches, 27,003 candidates, 5,614 kept) and sorted them into tiers. The strict top tier (topic, a medium or strong tie, the right place) holds fewer than 5 people in 23 of 27 searches. It is empty in 17.
- The lower tiers barely exist, because every lane asks for Belgian people. Only 1 cut candidate has a full topic match, a place inside the asked area and no tie. 487 cut candidates have a full topic match and no tie, all OpenAlex co-authors of Belgian works, and 352 of those live outside the US.
- Recommendation: a six-tier ladder that reorders the kept list, puts topic before tie, and lets topic experts without a tie back in from the `no_belgian_evidence` cut. It keeps the median list at 149 people, adds 135 people across 10 searches and leaves gold picks in the first 20 at 5. To fill the tiers without a tie, the web lane needs one extra search without "Belgium" in it, and parse has to say which wishes are hard.
- Show tiers as at most three section headings, named by the wishes they meet. This overrides the "no divider" part of D15.

## How FN orders today

- `rank.group`: group 0 is a topic match plus any Belgian tie kind (or a tie alone when the question has no topic words). Group 1 is everyone else.
- `rank.band`: five bands. Group 0 inside or unknown place, group 0 outside, group 1 inside or unknown, group 1 outside, then people placed only outside the question's country. Inside a band, more topic words come first, then the score.
- `rank.cut_reason`: four cuts, only for people whose records all come from OpenAlex: `no_belgian_evidence`, `weak_openalex`, `no_claim`, `outside_country`. In the snapshot: 12,931, 2,618, 5,021 and 819 cut people.
- `evidence.tie` names five kinds: `seed_list`, `belgian_org`, `belgian_text`, `belgian_place`, `institution`. Any one of them counts as a tie, with no grading.
- Every lane asks for Belgian people. The seed lists are Belgian by construction. The OpenAlex lane searches works with `institutions.country_code:BE` and institution authors with a Belgian affiliation. The web lane objective starts with "People with a connection to Belgium".

## 1. The wishes a question carries

| Wish | What the question says | Measured today | Field |
| --- | --- | --- | --- |
| Topic expertise | "about the US midterms" | yes: full match (every content word of one chip in one claim) or partial (some words) | `Topic.match`, `Topic.words` |
| Tie to Flanders or Belgium | "ideally connected to Flanders" | yes, as kinds, not graded | `Tie.kinds`, `Tie.years`, `Tie.last` |
| Place | "at our New York event" | yes, for a metro area: inside, outside, unknown, and abroad | `Where.fit`, `rank.abroad` |
| Kind of person | "business leaders", "founders", "faculty" | no. Parse has no field for it, so it lands in a topic chip or nowhere | none |
| Senior or speaker-ready | "could give a keynote" | no. `ask` holds talk, mentor, host, join, but nothing reads it | `Chips.ask`, unused |
| Recency | implied | partly: claim dates exist, and recency is used only for the employer's city | `evidence.recent` |

Numbers on the 5,614 kept people:

- 766 have a full topic match and 1,897 have at least one topic word (searches with topic words only).
- Place inside the asked area: 311. Outside: 2,214. Unknown: 3,089.
- A role or `works_at` claim: 3,627 (65%). A claim dated 2021 or later: 3,954 (70%).
- No tie kind at all: 749. 746 of those come from the web lane alone, and 200 of them have a full topic match.

Two facts from the 27 stored questions:

- 16 name a kind of person ("business leaders", "founders", "faculty", "designers", "advisers"), counted with a word list. In 2 searches nearly nobody can match the topic: 1,000 of 1,002 kept people sit in the lowest tier for "business leaders ... on small tech versus big tech", and 149 of 149 for "Flemish founders who have already expanded to the US". The topic chips there ("small tech versus big tech", "expanded to the US") are not fields of expertise. The real wish is the kind of person.
- 22 name a tie word in the ask itself. 2 more mention "Flanders House" only as the venue, and 3 have no tie word. So in 5 of 27 questions FN demands a tie that the question never asked for. None uses "ideally" or "preferably", so the soft case the owner describes is not in the stored set yet.

## 2. Three tier schemes, counted

Each scheme is run over every stored candidate, kept and cut. "Strong tie" is defined in section 4. Script and per-search output are in the scratchpad, not in the repo.

**Scheme A, strict ladder.** A: topic, strong tie, place fits. B: topic and any tie. C: topic, place fits, no tie. D: topic only. E: tie with some topic words. F: the rest. Place "fits" means inside the metro area, or not abroad when the question has no metro area.

**Scheme B, points.** Topic 3 (partial 1), tie 0 to 2 by strength, place fits 1. Tier by sum, from 6 down.

**Scheme C, topic first.** 1: topic and tie. 2: topic, no tie. 3: some topic words and a tie. 4: the rest.

| Scheme | Top tier: median per search | Searches with fewer than 5 in the top tier | Searches with an empty top tier |
| --- | --- | --- | --- |
| A | 0 | 23 of 27 | 17 |
| B | 0 | 23 of 27 | 17 |
| C | 8 | 11 of 27 | 7 |

Scheme A and B share the same top tier: topic plus strong tie plus place is rare. Scheme C reaches a top tier of 5 or more in 16 searches, because it drops place from the top.

Scheme A over kept and cut people, summed over all 27 searches: A 345, B 751, C 258, D 442, E 1,781, F 23,426. This first run still counted the institution chip as a tie (see section 4). The top tier is concentrated in three searches. The MIT faculty question has 208, a US-based advisers question 75 and a North Carolina question 46. Every other search has 0 to 8.

**Topic and place without a tie, among the cut people:**

- Full topic match, inside the asked metro area, no tie: 1 person, in 1 search.
- Some topic words, inside the area, no tie, not abroad: 29.
- Full topic match, no tie, any place: 487, all cut as `no_belgian_evidence`, all found by OpenAlex alone, in 10 searches. 352 are abroad, 123 have an unknown place and 1 is inside the area.

So the pool the owner wants for the lower tiers ("a political expert without a tie") is close to empty. The lanes never looked for those people. The OpenAlex co-authors of Belgian works who do appear are mostly researchers abroad, not the business people and professionals the owner asked for.

## 3. What the lanes must change for the lower tiers to exist

No lane asks for a topic expert without a Belgian tie today. Changes, with the extra calls each adds per search (calls per search read from `step_calls` over 26 lane runs):

| Lane | Today | Change | Extra calls per search |
| --- | --- | --- | --- |
| Web | 2 Parallel calls (search, extract), $0.0008; 15.5 page reads by the small model on average (12 to 21), $0.034 | A second Search request with an objective without Belgium: "People who work on {topics} in {place}", with the same queries | +2 Parallel calls (about $0.0008) and +12 to 21 page reads (about $0.034). Added time not checked |
| Web, cheaper | as above | Keep one request and make the objective neutral, so the Belgian tie becomes a ranking wish | 0 extra calls, but fewer Belgian people come back. Not measured |
| OpenAlex | 16 calls on average (1 to 31), 1.7 topic chips per search | A works search per topic chip filtered on the question's country (`institutions.country_code:US`), then the same author and institution batches | about +9 per topic chip, so about +15 per search (estimated from today's 16 for 1.7 chips) |
| Seeds | Belgian lists only | No change. Seeds are the tie tiers | 0 |
| Cuts | `no_belgian_evidence` cuts every OpenAlex-only person without Belgian years | Exempt a person with a full topic match who is not abroad | 0 calls; 135 people come back in the snapshot |

Run the second web request only when tiers 1 and 2 hold fewer than 20 people after the first lanes. In the snapshot that is 20 of 27 searches, so the gate saves about a quarter of the calls. The owner said Parallel limits will not grow. A local metasearch such as SearXNG could take the no-tie query instead. I did not check that here; it belongs to the open-source note.

The extra OpenAlex calls come from the same daily budget that ran out today. US works searches should return many more authors than Belgian ones (not checked). Cap them at one page per chip.

## 4. Grading tie strength

The kinds evidence already names, plus two claims FN stores but does not read as a tie:

| Grade | Rule | Kept people with it as their best grade |
| --- | --- | --- |
| Strong | on a seed list; or a Belgian degree (`studied_at` a Belgian organization); or born in Belgium; or at least 3 years at Belgian organizations with one since 2016 | 3,986 |
| Medium | a Belgian organization (shorter or older); or a stated place in Belgium | 611 |
| Weak | Belgian text only: a word such as Ghent, Leuven or Flemish in a claim | 268 |
| None | no kind | 749 |

Grades were computed with the institution chip left out. `institution` should stop counting as a tie: it says the person matches the question's institution (MIT), not that they have a link to Belgium. A Belgian institution chip (KU Leuven) already shows up as `belgian_org`. Today 0 kept people have `institution` as their only kind, so taking it out costs nothing measured.

Degrees and birthplaces add no new tied person today. 145 candidates hold a Belgian `studied_at` claim and 22 a Belgian `born_in` claim, and all of them already have another kind. They do lift 41 kept people from weak to strong, whose only other kind is Belgian text. They matter for the group the owner calls untapped: a professional whose only tie is a master's degree from a Belgian university. That person shows up only when the web lane's page read asks for degrees and the lane stops requiring a Belgian connection.

Weak ties are noisy. A city word in a paper title or a company name counts. 309 kept people have Belgian text as their only kind.

## 5. How the page should show tiers

D15 and its addition, quoted from the last round's design:

> "The heading stays "New", with no "Best matches" and no divider."

The owner's new wish ("better or worse results ... and the ranker takes it into account") overrides the "no divider" part. A list where position 9 has a Flemish tie and position 10 does not, with nothing on the page to say so, hides the drop in expectations the owner describes. The other part still holds: no heading claims "best". Headings name which wishes a person meets, which is a fact, not a quality claim.

| Option | For | Against |
| --- | --- | --- |
| Order alone | no new UI, D15 stays | the organizer cannot see where the tie stops |
| A label on every card | works across "Show 20 more" | 20 labels repeat what the why line already says |
| Section headings | one line per tier shows the drop | empty sections must hide, and a page of 20 can cross a boundary |

Recommendation: section headings, at most three, each with its count, and empty ones hidden:

1. "Topic and a tie to Flanders" (tiers 1 and 2)
2. "Topic, no known tie to Flanders" (tiers 3 and 4)
3. "Tie to Flanders, topic not confirmed" (tiers 5 and 6)

Place stays on the why line ("in New York", "elsewhere in the US", "place unknown"). It is not a heading. Paging stays 20 at a time and runs across the headings. A heading prints where its first person falls.

## 6. What parse must output

Today parse returns topic, institution and place chips and an `ask`. It does not return the tie, the kind of person, or whether a wish is hard or soft. The ranker assumes a tie is wanted always.

Add three things:

- `need` on every chip: `must` or `nice`. Rules for the prompt: a topic is `must`. A tie is `must` when it qualifies the person ("Which Belgian faculty", "Flemish founders"), and `nice` with "ideally", "preferably", "if possible" or when it is only the venue. A place is `nice` unless the question says "based in" or "who lives in".
- A `tie` chip: the span of the question that asks for the tie, with `need`. No tie chip means no tie wish, so the 5 stored questions without one stop demanding it.
- `roles` chips: the kind of person ("business leaders", "founders", "faculty"), matched against role claims, not topic claims.

How the ranker uses them: a `must` wish that a person does not meet puts them out of tiers 1 to 4. When the tie is `must`, tiers 3 and 4 are hidden. When it is `nice`, they show. Roles become a fourth wish that orders people inside a tier. It cannot define a tier yet: 35% of kept people hold no role claim. Each change to the prompt needs fixtures for the empty, duplicate and venue-only cases.

## Recommended scheme: the wish ladder

It is scheme A with two corrections from the counts. A tie and topic person who lives abroad drops to tier 4 instead of tier 2, as D12 already puts them last. And tiers only reorder the people FN keeps today, except for the topic experts the `no_belgian_evidence` cut lets back in. Inside a tier, today's order holds: band, topic words, score.

| Tier | Rule | Heading | Kept and added people, sum of 27 searches | Searches with 0 |
| --- | --- | --- | --- | --- |
| 1 | full topic match, tie medium or strong, place fits | Topic and a tie to Flanders | 361 | 17 |
| 2 | full topic match, any tie, not abroad | Topic and a tie to Flanders | 441 | 9 |
| 3 | full topic match, no tie, place fits | Topic, no known tie | 69 | 20 |
| 4 | full topic match, no tie and not abroad; or a tie and abroad | Topic, no known tie | 472 | 9 |
| 5 | kept today, a tie, at least one topic word | Tie, topic not confirmed | 1,062 | 10 |
| 6 | everyone else kept today | Tie, topic not confirmed | 3,344 | 2 |
| out | the four cuts, except a full topic match without Belgian years and not abroad | none | 21,254 | |

"Full topic match" holds by default when the question has no topic words. "Place fits" means inside the metro area, or not abroad when the question names no metro area.

Measured effects on the snapshot:

- Median shown per search: 149, the same as today. 135 people come back from the cut in 10 searches. The largest rise is in the climate question, from 204 to 263.
- Tiers 1 and 2 together hold fewer than 5 people in 13 searches and fewer than 20 in 20. Tiers 1 to 4 hold fewer than 5 in 9 searches.
- Today's first 20 already hold every tier 1 and 2 person they have room for: 214 of 214. The ladder changes the order below them. Today's first 20 (528 cards) hold 13 tier 3, 37 tier 4, 110 tier 5 and 154 tier 6 people. Tiers 3 and 4 move above tiers 5 and 6.
- Gold: 12 picks reach the candidates. 5 are in the first 20 today and 5 under the ladder, 6 in the first 50 under both. Two picks move up (GS-28#1 from 163 to 138, GS-28#2 from 77 to 74). Two move down below position 100: GS-02#3 from 138 to 182 and GS-15#3 from 104 to 161. No pick is lost.

## Cost to build

Judgement call, in dev-days:

- `evidence`: tie grades, degree and birthplace kinds, `institution` out of the tie. 0.5.
- `rank`: `tier()` in place of `group` and `band`; the cut exemption; a `tier` field on `Candidate` and in the database. 1.
- `parse`: `need`, the tie chip and role chips in the prompt and contracts, with fixtures. 1.
- Web lane: the second objective and the gate on tiers 1 and 2. 1. OpenAlex country works search: 0.5.
- Page: up to three headings with counts in `present.py` and the design system. 0.5 to 1.
- `fn-score`: tier sizes per search and "searches with fewer than 5 in tiers 1 and 2" as reported metrics. 0.5.

Total about 5 to 5.5 days. The cheap first step is the ranker and the evidence alone (1.5 days): it uses only stored data and can be checked with `fn-score rerank`. It changes little until the lanes find people without a tie.

## Risks

- **Noise from people without a tie.** The 135 people the cut lets back in are all OpenAlex-only. Their topic match rests on a work title, and they have no role and often no place. Tier 4 may fill with researchers the owner asked for less of. Limit tier 4 people added from the cut to 20 per search until a scorecard shows they help.
- **Weak ties lift people.** Belgian text alone puts 81 people in tier 2. Grading moves them under the strong ties inside the tier, not out of it.
- **More people to show.** With the second web request, each search reads 12 to 21 more pages. None of the people on them are in the snapshot, so the size of the rise is not checked.
- **Thin top tiers stay thin.** In 13 of 27 searches the first heading holds fewer than 5 people. The page then mostly shows the lower headings, and the organizer has to read them. That is what the owner asked for, but it looks worse than today's single list.
- **Parse errors become ranking errors.** A `must` read wrongly hides tiers 3 and 4. Default to `nice` when the model is unsure.
- **Gold set.** Only 12 picks reach the candidates. A move of one pick is a twelfth of the signal.
