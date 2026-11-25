# Panel records, round six

One panel of three ruled on three design decisions on 25 November 2026. Each panelist read the same brief through its own lens: spec and precedent, risk, and size. Two panelists ran on Opus and the size panelist on GPT Sol. The one split question went to a second round with new panelists, who saw the first round's answers. The brief, with the measured facts behind each option, is kept outside git with the research notes. The decisions are worked out in [design.md](design.md).

## 1. How a profile that Parallel read becomes claims

Options: (R1) FN's page reader as it is, a model call per chunk of the page; (R2) a parser for Parallel's labelled profile text that builds the fields the strict LinkedIn route already turns into claims; (R3) the page reader with a new prompt for profile pages and a 40,000-character limit.

Winner: R2, 3 to 0.

- **Spec and precedent**: the strict route's path from a profile to claims exists and needs no model call, and round four chose a rule over a model call for the same kind of step.
- **Risk**: on 12 of 94 stored LinkedIn pages the page reader gave claims to two to eleven people, which is how a collaborator gets facts that belong to the profile's owner. A text without the expected labels gives a trace row and no claims, so a change of format writes no wrong data.
- **Size**: R1 keeps the measured misses (a `studied_at` claim on 16 of 62 profiles that list a school), and R3 adds about seven model calls a profile that nothing asks for.

## 2. Where the Google route lives

Options: (I0) build nothing; (I1) a seventh lane beside `linkedin`; (I2) one `linkedin` lane with two routes, the strict scraper on a paid plan with budget and the Google route otherwise; (I3) the Google route replaces the strict scraper.

Winner: I2, 2 to 1 in round one and 3 to 0 in round two.

- **Spec and precedent**, I2 in both rounds: the owner asked for a route beside a scraper that stays, which is a fallback, and `check_account` is the switch that exists. A seventh lane adds a lane name and, on a paid plan, a second score part for one person. The OpenAlex lane already runs two queries inside one lane.
- **Size**, I2 in both rounds: one fallback route does what was asked.
- **Risk**, I1 in round one: the paid path stays untouched, and the benchmark's rule that a miss of the `linkedin` step is no fault would hide the Google route's misses. In round two the risk panelist chose I2: the pay check sits on the strict call itself, so a routing fault cannot start a paid run, and a seventh lane would need the same exemption.

Conditions the second round attached, all taken into the brief: the benchmark's exemption covers only misses that are off by design; the route is chosen by a recorded strict answer first and by the account second; the Google calls carry their own charge limit and make no account call; a test shows that a free plan, a plan without room and an unreadable account send no call to the strict scraper.

## 3. Which read profiles the lane keeps

Options: (K1) every profile read, as the strict route keeps every profile its scraper returns; (K2) only a profile whose education names a Belgian school; (K3) as K2, and only people in the US.

Winner: K2, 3 to 0.

- **Spec and precedent**: the strict scraper filters on the schools inside LinkedIn, so K2 keeps what the paid route would keep, and the scout lane drops people who are not leads before it stores their claims.
- **Risk**: K1 stores 33 of 89 measured profiles of people without a Belgian school. K3 adds a second place where an odd country value drops a real match.
- **Size**: K2 restores the school filter Google cannot enforce. The check must be for a Belgian school, since the alias file also holds schools abroad. K3 adds a restriction to the US that nobody asked for.

Noted by the risk panelist and kept as a known limit: the HTTP cache holds Parallel's full answer for every profile read, also for the ones the lane drops.

## 4. Review of the finished change

New panelists read the whole diff through the same three lenses, and all three approved it.

- Taken from the risk reviewer: a profile whose headline line is empty got its summary stored as the headline. The parser now reads a headline only from the line right after its label.
- Taken from the size reviewer: a test for an institution chip that is no school.
- Taken from the spec reviewer: the task file names a test helper that was split in two.
- Left as they are and listed in the design note: a scraper answer without a results list reads in the trace as "no profile address"; one profile under two spellings of its address is two records. A failed second ask of a query fails the lane's step, as every failed call in the lane does.
