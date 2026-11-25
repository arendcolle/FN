# Panel records, round five

One panel of three ruled on two product decisions on 25 November 2026, in two rounds. Each panelist read the same brief through its own lens: spec and precedent, risk, and size. Two panelists ran on Opus and the size panelist on GPT Sol. Round two used new panelists, who saw the first round's answers. The brief, with the measured facts behind each option, is kept outside git with the research notes. The decisions are worked out in [design.md](design.md).

## A. When a search spends money on the LinkedIn lane

Options: (A1) nothing by default, as before; (A2) every search with a query, while the month's budget has room; (A3) only searches that do not ask for researchers only, while the budget has room; (A4) only when staff press a button on the results page.

Winner: A3, 2 to 1 in both rounds.

- **Spec and precedent**, A3: it mirrors the rule that skips the OpenAlex lane when no research is asked, and the budget check copies the credit reserve of `fn-index`. A button would spend money in a place the owner has not seen.
- **Risk**, A3: paying on every search uses a month of about 24 runs in about ten days, after which LinkedIn people stop appearing without a word. When the budget cannot be read, the lane must serve recorded answers only.
- **Size**, A2 in both rounds: one budget check plus the cache delivers the request, and a gate on the kind of person is a rule the owner did not ask for.

Fact added for round two: the parse step reads "Economists in Chicago with a degree from KU Leuven" with a role that is not academic research, so A3 runs LinkedIn for all five benchmark questions that had nobody invitable.

Two facts came after the panel and changed the build, not the choice. Apify's free plan runs the actor ten times in total, so the lane makes no paid call on a free plan. A run of 25 full profiles does not fit in the actor's time limit, so a run takes 10.

## B. What may still change after a search is shown as done

Options: (B1) nothing, the page says done only after every step; (B2) the second lookup pass runs after done and the list is ranked once more when it added facts; (B3) as B2, and the cards keep the order saved at done; (B4) as B2, and a LinkedIn run that is still going also finishes after done.

Winner: B2, 2 to 1 in both rounds.

- **Spec and precedent**, B2: the design of round three names it as the next step, and since that round a lookup pass that added facts is followed by a new ranking. A frozen order would differ from what a later rerank produces.
- **Size**, B2: it reuses the ranking with stored verdicts and the existing swap of the list. B3 adds a rule to freeze the order, B4 a second way for a lane to end.
- **Risk**, B3 in both rounds: a list that moves under a reader right after the count line appears, and a next search that waits behind the pass.

The dissent is met in part. While the pass runs, the page says "Looking up missing facts…" under the count line, and the swap waits while the pointer or the focus is on a card. The pass stays on the one worker thread, and a step left running on a done search is interrupted at the next start. The next search still waits behind the pass, as it waited before.
