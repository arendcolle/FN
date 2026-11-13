# Is a result list good enough for Paul to invite from?

## TL;DR

Today `fn-score` counts gold picks, kept people, doubles and the share of cards with a topic word or a place. Nobody judges whether the first ten people are worth inviting. This note adds that judgement: 14 new questions in Paul's voice that ask for business people and professionals, and a rubric that three judges apply to each of the first 20 cards. The hill-climbing target is the number of invitable people in the first 10 (I10), summed over the 10 development questions. The 4 held-out questions and the existing gold gates guard against overfitting. "Drastically better" means I10 at least doubles from a baseline still to be measured, with at least 3 invitable people in the first 10 on 8 of 10 development questions. The questions also exist as JSON with the same fields, for the harness that runs them.

## What is measured today and what is missing

`src/fn/score.py` reports, per stored search: gold picks at positions 10, 20 and 50, people kept, doubles, card fields filled, topic word found, place inside or outside, and which lanes found each card. On the final snapshot (replay, 31 searches, scorecard read from the last round's run) the first 20 cards were:

- found only by OpenAlex: 0.43
- found only by seed lists: 0.36
- found only by the web lane: 0.17
- found by two or more lanes: 0.03
- with a role shown: 0.46, with a place shown: 0.45

Gold picks in the first 20 were 13 of 99. None of these numbers says whether Paul would invite the person. A card with a topic word, a place and a Belgian organisation can still be a retired professor in the wrong field. The share of researchers in the first 20 is not measured; the OpenAlex-only share (0.43) is a lower bound for it, because some seed and web cards are academics too (not checked).

## The 14 questions

The dimension of the split is domain, crossed with place and with how hard the tie is. Six questions require a tie (must), five wish for one (ideal), three ask for none. None asks for a researcher. The gold set covers AI, telecom, start-up founders, Atlanta business leaders, fashion, ocean, climate and health data, so those topics are left out. Split: 10 for development (dev), 4 held out (hold).

Each entry gives the question, the must wishes, the nice-to-have wishes, and an ideal (I), acceptable (A) and fallback (F) speaker.

**BQ-01** (dev, politics, New York, travel allowed, tie ideal). "Who could speak about the US midterms at our New York event, ideally someone connected to Flanders who works in or close to US politics?" Must: works now in or close to US politics (campaign, polling, party, Congress staff, political journalism or analysis). Nice: tie to Flanders or Belgium; based near New York. I: a New York pollster or strategist who grew up in Flanders and comments in US media. A: a Washington analyst with no tie, or a New York political reporter who studied a year in Leuven. F: a Belgian-born political science lecturer who writes op-eds.

**BQ-02** (dev, media business, Atlanta, tie ideal). "Who in Atlanta's film and TV production business could talk to Flemish animation and visual-effects studios about working on US productions, ideally someone with a Belgian tie?" Must: works in film or TV production or studio business; can speak about how US productions hire outside studios. Nice: Belgian tie; based in Atlanta. I: an Atlanta studio executive who started at a Flemish animation studio. A: an Atlanta post-production supervisor with no tie, or a Belgian-born producer in Los Angeles. F: a Georgia film commission officer.

**BQ-03** (dev, finance, New York, tie must). "Who works in finance in New York and studied in Flanders, for a panel on transatlantic investment in Flemish scale-ups?" Must: studied at a Flemish university or business school; works in venture capital, private equity, banking or asset management. Nice: invests in European companies; based in New York. I: a venture partner with a Flemish master's degree who backed a Belgian start-up. A: an investment banker with a Flemish degree in another sector. F: a Flemish-educated finance professional in Boston.

**BQ-04** (dev, technology companies, Bay Area, tie must). "Which product or engineering leaders at Bay Area tech companies have a Flemish background and could judge a start-up pitch night in San Francisco?" Must: born, raised, studied or worked in Flanders; product, engineering or founding role at a tech company. Nice: based in the Bay Area; has founded or funded a start-up. I: a director of engineering who studied in Ghent and mentors founders. A: a senior engineer with a Leuven degree and no lead role shown. F: a Flemish founder in Los Angeles.

**BQ-05** (dev, law, Washington, online so anywhere in the US, tie ideal). "Who could explain US export controls and sanctions to Flemish companies in a webinar? A Washington trade lawyer would be ideal; a Belgian link is a plus." Must: practises or advises on export controls, sanctions or trade compliance. Nice: based in Washington; Belgian or EU tie. I: a Washington trade-compliance partner who trained in Brussels. A: a Washington export-control lawyer with no tie. F: a former Commerce official now consulting, place not shown.

**BQ-06** (dev, media, New York, tie must). "Which journalists or editors in New York who grew up in Belgium could moderate our evening on press freedom?" Must: born or raised in Belgium; journalist, editor or media executive. Nice: based in New York; has moderated panels. I: a New York correspondent for a Flemish paper, raised in Antwerp. A: a Belgian-born magazine editor in New Jersey. F: a Belgian-born communications director with a journalism past.

**BQ-07** (dev, culture, Chicago, tie ideal). "Who in Chicago could open our Flemish Masters exhibition evening, a museum or gallery person, ideally with a tie to Flanders?" Must: works at a museum, gallery, auction house or arts organisation; can speak about Flemish art to a general audience. Nice: Flemish tie; based in Chicago. I: a Chicago curator of European paintings who trained in Antwerp. A: a Chicago gallery director who has shown Flemish artists. F: an art historian at a Chicago university.

**BQ-08** (hold, sport, Texas, no tie). "Who works in US sports business in Texas, such as club management, sponsorship or events, for a talk on what Belgian sports clubs can learn from American ones?" Must: works now in sports business. Nice: based in Texas; tie to Belgium or European football or cycling. I: a Dallas club's commercial director who grew up in Belgium. A: a Houston venue sponsorship manager. F: a sports marketing consultant in another state.

**BQ-09** (dev, food and drink, anywhere in the US, tie must). "Which Belgian brewers, chocolatiers or food entrepreneurs who built a business in the US could speak at our food export seminar?" Must: Belgian by birth, upbringing or study; founded or runs a US food or drink business. Nice: business has Belgian roots; has spoken in public. I: the Flemish-born founder of a US brewery that brews Belgian styles. A: the Belgian-born manager of a Belgian chocolate brand's US arm. F: a Belgian-born restaurant owner.

**BQ-10** (hold, diplomacy and security, Washington, no tie). "Who could speak on NATO burden sharing and transatlantic security at a Flanders House event in Washington, from a think tank or a former government role?" Must: works on NATO or transatlantic security at a think tank, or held a government or military role on it. Nice: based in Washington; knows the Belgian or EU view. I: a think-tank fellow who served at the US mission to NATO in Brussels. A: a defence analyst at a consultancy. F: a security journalist in Washington.

**BQ-11** (dev, energy and ports, Houston, tie ideal). "Who in the Houston energy or port world could talk about offshore wind and hydrogen supply chains with the Port of Antwerp-Bruges, ideally someone who has worked with Belgian firms?" Must: works in energy, ports or maritime logistics; knows offshore wind, hydrogen or energy supply chains. Nice: worked for or with a Belgian firm; based in Houston. I: business development lead at the Houston office of a Flemish dredging group. A: a Houston port manager for energy cargo. F: an energy consultant elsewhere on the Gulf Coast.

**BQ-12** (hold, life sciences business, Boston, tie must). "Which business development people or investors in Boston life sciences studied at a Flemish university and could advise Flemish biotech start-ups on raising money in the US?" Must: studied at a Flemish university; business or investor role, not a lab role. Nice: based in Boston; has raised or invested money. I: a Boston biotech investor with a Flemish master's on start-up boards. A: a Cambridge business development director with a Flemish degree. F: a Belgian investor in New York.

**BQ-13** (hold, business and trade, Chicago, no tie). "Who in Chicago could talk about food and agriculture trade with Belgium, such as an importer or a commodities trader?" Must: works in agricultural or food trade. Nice: trades with Belgium or the EU; based in Chicago. I: a Chicago grain trader whose desk ships to Antwerp. A: a Chicago importer buying across the EU. F: a Midwest farm trade association officer.

**BQ-14** (dev, work and careers, anywhere in the US, tie must). "Which Belgians who moved to the US mid-career could speak online to Flemish professionals about working in America: visas, culture and pay?" Must: Belgian by birth, upbringing or study; moved to the US as an adult and works there now, any profession. Nice: Flemish; has written or spoken about the move. I: a Flemish engineer who moved to Texas at 35 and blogs about it. A: a Belgian-born nurse or accountant in the US with no public talks. F: a Belgian who studied in the US and stayed.

## The judge rubric

A judge sees one question (with its must and nice wishes) and one card with its person page. The judge scores four criteria and writes one sentence of reason per criterion. Card score = topic + tie + place + invite, from 0 to 10.

Rules that hold for every criterion:

- Score only what the card and person page show. A claim without a source link, or whose source excerpt does not support it, counts as absent.
- The name is replaced by "Person A". The judge sees only a flag that says whether a full name is present. This stops a model judge from using what it knows about a real name.
- When unsure between two levels, take the lower one.
- An organisation, a duplicate of a card higher in the list, or a page about someone else scores 0 on every criterion.

### Topic fit (0 to 3)

- 3: the person's current job is the must topic.
- 2: the current job is in the field but a neighbouring specialty, or the topic was their job within the last five years.
- 1: only a loose link: same broad sector, a keyword in a title, a single article.
- 0: no link, or the word matched in another sense.

Examples for BQ-05 (export controls). Score 3: "Partner, trade compliance and sanctions, a Washington law firm", source is the firm's bio page. Score 2: "Customs and tariff counsel at a Chicago firm", no export-control work shown. Score 0: "Product manager, data export tools", the word matched in another sense.

### Tie to Flanders or Belgium (0 to 3)

- 3: a sourced personal tie to Flanders: born or raised there, a degree from a Flemish institution, or a year or more at a Flemish employer.
- 2: a sourced personal tie to Belgium outside Flanders (Brussels, Wallonia, a federal body), or a sourced working tie to Flanders: a board seat at a Belgian-American chamber, a job at the US arm of a Flemish firm.
- 1: a weak or inferred tie: one co-authored paper, one event appearance, a Belgian-sounding surname with one hint, or a tie the card states without a source.
- 0: no tie shown, or a tie the sources contradict.

When the question asks for no tie, judges still score it, because it can lift a card, but it never blocks invitable. Examples: "Master's, a Flemish university, 2009", source is a LinkedIn-style profile excerpt: 3. "Board member, a Belgian-American chamber in Atlanta", source is the chamber page: 2. "Spoke at a Flanders House event, 2019", one event page: 1.

### Place fit (0 to 2)

- 2: the card shows a current place inside the asked metro or state; for "anywhere in the US" or an online event, any US place.
- 1: a US place outside the area when the question allows travel; or no stated place but a current employer whose city is inside the area.
- 0: outside the US, outside the area when the question asks for a local speaker, or no place information at all.

Examples for BQ-13 (Chicago): "Based in Chicago, IL" from a company page: 2. "Lives in Milwaukee": 0, because BQ-13 asks for a local speaker. No place, employer is a trading firm whose office the card puts in Chicago: 1.

### Could Paul invite on what the card shows (0 to 2)

- 2: the identity is clear (full name, current role and employer), the main claim has a source, and the newest dated fact is at most five years old.
- 1: one gap: role or employer missing, newest fact older than five years, or the main claim unsourced.
- 0: two or more gaps, the person cannot be told apart from namesakes, or the card says they died, retired from all work or left the field.

Examples. "Person A, Chief Commercial Officer, a Dallas soccer club", club staff page dated 2026: 2. Same but no role, only "a Dallas soccer club", page from 2018: 0 (two gaps). Full name and role, one undated web mention as the only source: 1.

### Invitable

A card is invitable when all of these hold:

- topic 2 or more
- invite score 2
- tie 2 or more if the question's tie rule is must
- place 2 if the question is local (metro or state); place 1 or more if travel is allowed

### A person the judge cannot verify

A judge never searches the open web. A card whose claims have no source, or whose sources do not support them, scores as if those claims were absent, which usually gives invite 0 or 1. The card stays in the list and in every denominator. A judge marks "cannot tell" only when the card and page disagree with each other; such a card scores 0 on invite and goes to discussion.

### Researcher

For the non-researcher share, a card counts as a researcher when its role is an academic research job (professor, lecturer, postdoc, PhD candidate, research scientist) at a university or public research institute, or, with no role shown, when every source is bibliographic (OpenAlex, ORCID, a paper). A scientist at a company is not a researcher. "Cannot tell" counts as a researcher, so the share cannot rise by hiding roles.

## List-level numbers

Per question, from the first 20 cards in the order FN shows them:

| Number | Definition |
| --- | --- |
| M10 | Mean card score (0 to 10) of positions 1 to 10. An empty slot scores 0. |
| I10 | Invitable cards in positions 1 to 10. |
| I20 | Invitable cards in positions 1 to 20. |
| NR20 | Share of positions 1 to 20 that are not researchers. Empty slots are left out of the denominator. |
| Z10 | 1 when I10 is 0, else 0. Summed, it counts questions where Paul gets nothing usable on the first screen. |

Totals sum I10, I20 and Z10 over questions and average M10 and NR20. Dev and held-out questions are reported apart.

## How three judges combine

Three independent judges score each card. The card's score per criterion is the median of the three. Invitable follows from the median scores, not from a vote. Judges must discuss a card when:

- any criterion's highest and lowest score differ by 2 or more
- two judges say invitable and one does not, or the reverse, and the card is in the first 10
- any judge marks "cannot tell"

In a discussion each judge reads the other two reasons and scores once more. If a spread of 2 remains, the lead decides and logs the card id and the reason.

Before a run, each judge scores the worked examples above. A judge that misses more than two goes back to the prompt, not into the run. To know the noise, the baseline is judged twice by fresh judges. A change counts only when its I10 gain exceeds twice the difference between those two baseline runs.

## The hill-climbing target and pass lines

The target is total I10 over the 10 dev questions. It is the number closest to Paul's job: how many people on the first screen he could write to. M10 breaks ties between versions with equal I10. Guards that must not get worse:

- held-out I10 total (catches overfitting to the dev questions)
- gold picks in the first 20 from `fn-score` (13 of 99 on the final snapshot)
- pairs of one person in a first 20 and labelled-different pairs on one card, as gated today

Proposed pass lines for "drastically better" against the baseline B, measured on current main:

| Number | Pass line |
| --- | --- |
| Dev I10 total | at least 2 x B, and at least 30 (3 per question) |
| Dev questions with I10 of 3 or more | 8 of 10 |
| Dev Z10 total | at most 1 |
| Dev mean M10 | B + 2.0 or more |
| Mean NR20 | 0.70 or more |
| Held-out I10 total | at least 1.5 x its own baseline |
| Gold picks in first 20 | no fall |

The lines above 30 and 0.70 are a judgement call; the baseline may already exceed one of them, and then the 2 x B line decides.

## What a judge may look at, and why

A judge may read only the question with its wishes, the card (role, employer, place, organisations, tie evidence, why line, combined-records line, source links) and the person page FN shows behind it, including the source excerpts stored there. Nothing else.

- Paul decides from these two screens. A score from the open web would credit FN for facts it never showed him.
- An open-web judge fills gaps, so a thin card would score as well as a full one. The rubric's job is to punish thin cards.
- The score must be repeatable. The stored page does not change between judges; the web does.
- The run stays inside the outside-call limits and sends no person's name to any service.

Facts the page shows can still be wrong. A separate audit outside the score covers this: the lead checks 10 cards judged invitable per round against public sources and reports false ties or stale roles as a count.

## How the benchmark runs

The 14 questions have no stored searches, so the scorecard's replay mode cannot run them yet. Each must run live once on main, recorded with `FN_LLM=record` and the HTTP cache, so later ranking changes can replay. A change to a lane needs new live runs. The cost of 14 live searches in Parallel calls was not checked. One live search took 68 s on the owner's server (progress log).

Proposed `fn-score` addition: a `judge` command that exports the first 20 cards of each benchmark search with names masked, and a `bench` metric block (M10, I10, I20, NR20, Z10) read back from the judges' JSON. Judging is a model call per card per judge: 14 x 20 x 3 = 840 calls per round, which needs its own budget (not checked).

## Not checked

- The baseline M10, I10, I20, NR20 and Z10 on current main.
- Whether a model judge agrees with the owner on invitable cards. A 20-card spot check by the owner before the first climb would settle it.
- The researcher share in the first 20 today; only the OpenAlex-only share (0.43) was read.
