# Which questions does FN stop asking, and what does a person page stop repeating?

Round four, 24 November 2026. The owner used FN for a week and came back with five things. This page records what was decided for each, why, and who owns what in the code. The votes are in [panel-records.md](panel-records.md), the steps in [progress.md](progress.md) and the task of each slice in [tasks/](tasks/).

## TL;DR

FN asked "is this the same person?" in places where it could answer itself or where the answer did not matter, showed one fact on several lines, and let staff type two contact details but not a third. This round an import reads the address FN's own export writes, a person page asks about namesakes only for people in the network, two records stand side by side wherever FN still asks, a person page shows one line per fact, and contact details are read-only with one behaviour. The lookup step also keeps pages it used to drop. The deployment plan became a one-page decision with a short plan per option, kept outside git.

## What the owner reported

| # | Report | Measured |
| --- | --- | --- |
| 1 | The lookup drops a page when the model's quote lacks the person's name | 12 of 77 recorded page readings, all 12 about the right person; 6 of 13 lookups that ended "not sure" |
| 2 | A person page shows the same fact several times under Work, Ties and Places | 2,125 of 37,897 pages show at least one such pair; one example page showed 14 Work lines for about 7 facts |
| 3 | Email and phone can be edited, LinkedIn cannot | The only typed facts in FN; no staff edit was ever made on the owner's database |
| 4 | The import check page asks "same as …?" and makes the user scroll and open pages to compare; the number of people to judge has to go down, for search results too | The owner's own export, imported again, asked 8 questions in 14 rows; 605 of 6,703 result cards lead to a page that lists namesakes |
| 5 | The deployment plan is too long and covers one way of delivering | 20,000 words in four files |

## Decisions

| Id | Decision | Why | Slice |
| --- | --- | --- | --- |
| L1 | In the lookup, a located mention whose quote lacks the model's name still counts when the model's name is the person and the page writes a name form of the person inside the quote or at most 1,000 characters before it. The held-fact check stays. | The model often quotes the title line under a name heading, which its prompt allows. Deterministic, no new model call, every recording still replays. | h1 |
| D1 | Staff type nothing about a person. Contact shows up to three rows, Email, Phone and LinkedIn, with the value and where it came from. Email and phone get "Not correct". | Contact values drive neither search nor ranking, an import brings details in, and a typed LinkedIn address would become an identifier that can block a true merge. Panel, unanimous in round two. | h3 |
| L3 | The LinkedIn row has no action. | Its address is the address of a record, not a fact read from a page. A wrong one means a wrong record, and "Not this person" under Sources separates that. | h3 |
| D2 | An import row whose `profile` cell is the address of a person FN holds, with that person's name, belongs to that person without a question. A name plus matching details still asks. | The address holds FN's own id for the person, so it is an identifier. A name never is. Panel, unanimous. | h4a |
| L2 | An unticked box on the import check page stores no "different person". | The box starts unticked, so leaving it is not an answer. The pair stays a possible match on the person's page, where the answer is explicit. | h5 |
| D3 | Only a network person's page lists possible matches. A search result's page asks nothing about namesakes. The card still asks when a namesake of a network person is added. | 684 of the 900 listed pairs share only a name or a first initial, on pages ranking never reads. Panel, unanimous. | h5 |
| L4 | Wherever FN still asks, the two records stand side by side in one table, field by field, with "Differs" on a row whose values disagree. | The owner's request. One view and one renderer serve the import question, a possible match and a search result with a network namesake. | h5 |
| D4 | The person page folds what the data says is one fact: lines that read the same, one Work line per organization, places at the same spot. Two or more titles without an employer are gathered in one line, "Also described as …", which opens into one line per wording. "Not correct" on a folded line removes every fact it folds. | The fold sits where the page is built, so no stored fact changes. A gathered line keeps every wording visible and needs no word list. Panel, 2 to 1; the dissent (one click must not remove every title) is met by leaving "Not correct" off the gathered line. | h2 |

Not decided by rule or by the model: whether two people with one name and matching details are the same. The panel refused that for imports and for network people, because no "different person" answer exists yet to measure a rule against.

## Design system

Version 14 adds the Compare part and changes ImportSummary, Profile, Claim and PersonCard to match the decisions above. The app's style sheet is a byte copy of the design system's.

## Deployment

The owner asked for the reason behind a way of delivering and for the options side by side, from "the customer runs everything" to "we host a service". The answer is a decision page and four short plans, reviewed by a council of two models. They hold prices and stay outside git, next to the earlier plan.

## Who owns what

| Responsibility | Owner |
| --- | --- |
| Whether a name is the looked-up person | `deepen.named_as` |
| Where a page writes a name form, and keeping a mention at its quote | `extract.name_forms`, `extract.anchored` |
| The strict mention check for the search lanes | `extract.check` |
| Reading a profile address, tying a row to a person, the row's coordinates | `importer.profile_id`, `importer.rows_of` |
| The name of the export's last column | `contracts.PROFILE_COLUMN` |
| Which lines of a person page are one fact | `present.fold_lines`, `present.lines_of` |
| The gathered titles line | `present.titles_of`, `parts.titles_line` |
| Removing every fact a folded line folds | the reject route with the line's `fold_ids` |
| The contact rows and where each value came from | `present.contact_of`, `present.linkedin_of`, `parts.contact_block` |
| The two sides of a comparison, their order, "Differs" | `present.compare_view`, `present.person_sides`, `present.row_side` |
| The comparison's markup | `parts.compare_table` |
| Which pages list possible matches | `present.profile` |
| Pairs, merges and "different person" answers | `network.py`, unchanged |
| The style sheet | the design system; `fn.css` is a byte copy |

## Measured after

| What | Before | After |
| --- | --- | --- |
| Recorded lookup page readings that count, of 77 | 51 | 62 |
| Questions when the owner's export is imported again, of 14 rows | 8 | 0 |
| Pages that show a line twice word for word | 1,681 | 0 |
| Work lines on the example page | 14 | 9 |
| Result cards that lead to a page listing namesakes, of 6,703 | 605 | 0 outside the network |
| Facts staff can type | email, phone | none |
| Tests | 1,127 | 1,176 |

## What is left

- No pair is decided by rule or by the model. Network people keep their possible matches until a user answers, and an import still asks for a name without an identifier or a profile address.
- An unticked import row stores no answer, so the pair shows again as a possible match on both pages.
- The long lists of publication affiliations under Work stay: "Show n more" is on about 22,000 pages, and duplicates explain under 1% of it.
- A looked-up page read a second time is stored as a second copy (6 addresses today).
- A folded line shows the source of the fact that names it, not every source it folds.
- The lookup's name rule still refuses a formal first name against a short one and a "Surname, First" entry, and one employer's short brand name is missing from the alias file.
- An import cannot be undone as a whole, and the check page says "Import 14 people" for a file that changes nothing.
- Two older tests are timing-sensitive under load.
