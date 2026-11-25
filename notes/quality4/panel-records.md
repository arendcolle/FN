# Panel records, round four

One panel of three ruled on four product decisions on 24 November 2026, in two rounds. Each panelist read the same brief through its own lens: spec and precedent, risk, and size. Two panelists ran on Opus and the size panelist on GPT Sol. Round two used new panelists, who saw the first round's answers. The brief, with the measured facts behind each option, is kept outside git with the research notes. The decisions are worked out in [design.md](design.md).

## D1. What staff can type by hand about a person

Options: (a) leave email and phone editable and LinkedIn not shown; (b) no typing, contact details read-only with a LinkedIn link; (c) email, phone and LinkedIn all editable the same way; (d) every fact editable.

Winner: option b. Round one 2 to 1, round two unanimous.

- **Spec and precedent**, round one, option c: the owner asked for one behaviour across the three, and the edit path for email already exists.
- **Risk**, option b: a LinkedIn address typed with a typo becomes an identifier that blocks the true record from merging, and nobody would see why. Nobody has typed a contact detail so far, and the CSV round trip brings details in.
- **Size**, option b: contact values drive neither search nor ranking, and read-only rows keep FN on searching.
- **Spec and precedent**, round two, option b: a LinkedIn Edit could only add a second address beside the one a record holds, so option c only looks like one behaviour. Read-only rows with "Not correct" behave the same for all facts.

Fact added for round two: a found email or phone had no "Not correct", so Edit was the only way to remove a wrong one. Under option b both rows get "Not correct".

## D2. When an import row updates a person without a question

Options: (a) every name match asks; (b) read the `profile` column of an FN export; (c) b plus a name with matching details; (d) c plus a name alone.

Winner: option b, unanimous in round one.

- **Spec and precedent**: a name is never an identifier in FN. The `profile` column holds FN's own id for the person, so it is one.
- **Risk**: option b removes all eight questions of the owner's import with no chance of a wrong match. Matching on a name plus one detail merges namesakes at a large employer, and an import cannot be undone as a whole.
- **Size**: it reuses an identity FN already wrote, with no new comparison rule.

## D3. When a person page asks about namesakes

Options: (a) every page lists every possible match; (b) only a network person's page does, and the card still asks when a namesake of a network person is added; (c) every page, plus "None of these"; (d) b, and pairs the rules grade as likely merge without a question.

Winner: option b, unanimous in round one.

- **Spec and precedent**: possible matches exist to find duplicates inside the network, and the question at the moment of adding stays.
- **Risk**: 684 of the 900 listed pairs share a name only or a first initial only, on pages ranking never reads. Option d would merge into network people on a rule nobody can check, because no "different person" answer exists yet.
- **Size**: a visibility rule, no new mechanism.

## D4. When two lines on a person page count as one fact

Options: (a) leave as is; (b) fold lines that read the same, one Work line per organization, places at the same spot; (c) b plus a word list that maps Dutch and French titles to English; (d) b plus one line that gathers every title without an employer.

Winner: option d, 2 to 1 in both rounds.

- **Size**, option d: option b leaves the owner's example with five wordings of one post on five lines. One gathered line fixes that without a word list to maintain.
- **Spec and precedent**, round two, option d: the gathered line follows the existing "Also named at n other organizations" line.
- **Risk**, both rounds split. Round one, option d: every wording stays visible and no list can fold two titles wrongly. Round two, option b: one "Not correct" on a gathered line would remove every loose title at once, true ones included.

The dissent is met in the build: the gathered line has no "Not correct" of its own. Opened, it lists each wording as its own line with its own "Not correct".
