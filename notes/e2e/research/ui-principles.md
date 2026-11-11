# UI principles checklist from the knowledge base

This note turns the owner's knowledge base into a checklist for UI decisions. It lists 19 principles with the page each comes from, then says what each principle demands of eleven screen types. Citations name the knowledge-base page, not a file and line. Anything not stated by a page is marked "general knowledge". The note proposes no design.

## Principles

| Principle | Knowledge-base page | Rule |
|---|---|---|
| Every state answered | state-coverage | At every step of a flow the user sees what just happened, how to take it back and what to do next. |
| Cover the rare states | state-coverage | Check stopped early, offline and empty first, because generated screens only give the success state. |
| Failure recovery | failure-state-design | Each failure tells the user what happened, what is safe and one action to take. |
| Break it on purpose | failure-state-design | Turn off the network mid-flow, fail an action and empty every list, then design those states. |
| One pattern per repeated situation | cross-screen-consistency | Running out, empty, confirm and error each get one layout, wording and set of facts, used on every screen that reaches them. |
| Use it for an hour | cross-screen-consistency | Find drift by using the product as a user, not by reviewing screens one at a time. |
| Conservation of complexity | conservation-of-complexity | Cut what the task does not need, then let the system carry the rest instead of the user. |
| Postel's law | conservation-of-complexity | Accept messy input, translate it to one strict form, and say clearly when the meaning is not clear. |
| Jakob's law | familiarity-and-response-time | Copy patterns users already know from other products. |
| Doherty threshold | familiarity-and-response-time | Respond within 400 ms, and fill any longer wait with visible progress. |
| Aesthetic-usability effect | familiarity-and-response-time | A pleasing look can hide usability problems, so test function separately from looks. |
| Hick's law | hicks-and-fitts-laws | Decision time grows with the number of choices, so cut or stage choices and highlight the recommended one. |
| Fitts's law | hicks-and-fitts-laws | Make important controls large and close to the task area. Do not strip the screen until the user cannot tell what to do. |
| Miller's law and chunking | memory-and-attention-laws | Group content into chunks. Do not treat seven items as a hard cap. |
| Von Restorff | memory-and-attention-laws | Make the one key action distinct, with restraint, and not by colour alone. |
| Zeigarnik and goal gradient | memory-and-attention-laws | Show progress and signs that more content exists. |
| Peak-end | memory-and-attention-laws | Name the one moment to be remembered and design the last screen of a flow with care. |
| Commodity ceiling | commodity-ceiling | Spend effort on what a prompt cannot copy: every state covered, one coherent product, failures handled well. |
| Gestalt grouping | gestalt-principles | Use proximity, similarity, enclosure, closure and connection to group, and check that the groups the reader sees are the ones intended. Before adding a border or divider, check whether proximity already does the job. |
| Four product risks | four-product-risks | Before building a feature, name which of value, usability, feasibility and viability is still a guess and pick the cheapest test. |
| Opportunity solution tree | opportunity-solution-tree | Place a feature on a tree under the customer need it serves and the outcome above that. A feature with no need above it has no place yet. |
| Ask about the past | customer-interviews | Evidence of value is the last time the problem happened and what the user did about it. Praise for an idea is not evidence. |
| Do it by hand first | do-things-that-dont-scale | Do the work by hand for a real user before automating it. |
| Comparing options | comparing-options | Ask first whether the choice is a one-way or two-way door. Reversible choices need a decision more than a method. |

The knowledge base has no page on user story mapping, jobs to be done or a usability evaluation method. The index has no entry for them (grep of index.md). For the value test of a feature, the pages above are the nearest: four-product-risks, opportunity-solution-tree and customer-interviews.

## Value test for a feature

Ask these five questions before a feature goes on a screen.

1. Which user need does it serve, in the user's words, and which outcome sits above it? (opportunity-solution-tree)
2. When did a user last have this problem, and what did they do about it? If the answer is a guess, the value risk is open. (customer-interviews, four-product-risks)
3. Is there a hand-made version the owner can use first? (do-things-that-dont-scale)
4. Can the user find and use it, and what is the cheapest check? A prototype in front of the owner is one. (four-product-risks)
5. Is it reversible? If it is, build the smallest version and learn. (comparing-options)

## What each principle demands of a screen

### A list of people with filters

- Show the count of results and the active filters next to the list, so the user sees what just happened after each change. (state-coverage)
- Offer one clear way to remove each filter and one to clear all, so every filter change can be taken back. (state-coverage)
- Give the list an empty state, a loading state and an error state, each with a next action. (state-coverage, failure-state-design)
- Group filters by meaning (place, topic, availability) with whitespace between groups, not borders on every control. (gestalt-principles)
- Stage the filters. Show the few used most, and put the rest behind a "more filters" control. (hicks-and-fitts-laws)
- Start with the recommended or highest-ranked rows and mark them. Do not present the whole list as equal. (hicks-and-fitts-laws)
- Respond to a filter change within 400 ms, or show progress. (familiarity-and-response-time)
- Use the familiar table or list-with-search layout, not a new pattern. (familiarity-and-response-time)
- Make the row action targets large enough to hit and close to the row they act on. (hicks-and-fitts-laws)
- Let a filter that accepts typed text take messy input, such as "NYC" or "new york", and translate it, and say when it cannot. (conservation-of-complexity)
- A filter that matches zero people names the filter that caused it and offers to relax it. (failure-state-design)

### A map with a list beside it

- Connect the two views. Selecting a row highlights its map marker and the reverse, since elements joined by shared state read as one thing. (gestalt-principles)
- Keep one colour for one series or status across the map and the list. (gestalt-principles)
- Show how many people lack a place and so are not on the map, so the user knows the map is not the full list. (state-coverage, answers "what just happened")
- Drop map furniture such as extra frames and gridlines. (gestalt-principles)
- Give the map an empty state and a failed-tiles state with a next action. (failure-state-design)
- Make marker targets large enough to select and spaced out; group nearby markers into chunks with a count. (hicks-and-fitts-laws, memory-and-attention-laws)
- Use standard map controls (zoom, pan, reset) in their usual places. (familiarity-and-response-time)

### An upload-and-import form with a preview

- Accept messy input (column order, header spelling, date and phone formats), translate it to one form and report what could not be read. (conservation-of-complexity)
- Show a preview of the first rows as they will be stored, with each rejected row and the reason. (state-coverage, failure-state-design)
- Ask for as few decisions as possible before the preview. Map columns automatically and let the user correct a mapping, not build one. (conservation-of-complexity, hicks-and-fitts-laws)
- Make the commit button the one distinct action on the screen, labelled with the count it will write. (memory-and-attention-laws)
- State what happens on commit, how to undo it and what to do next, before the click and again after. (state-coverage)
- Show progress for a big file, with a count of rows done. (familiarity-and-response-time, memory-and-attention-laws)
- Handle a wrong file type, an empty file, a file with no recognised columns and a half-finished import, each with what is safe and one action. (failure-state-design)
- The last screen shows what was added, what was skipped and a link to the result. This is the end moment of the flow. (memory-and-attention-laws)
- Do not claim the form passes just because it looks tidy. Test it with a bad file. (familiarity-and-response-time, aesthetic-usability effect)

### A duplicate or merge decision

- Show the two records side by side, with matching fields grouped and differing fields marked, so the user compares by proximity. (gestalt-principles)
- Mark the one recommended choice and make it the distinct action; keep the choices to a few. (hicks-and-fitts-laws, memory-and-attention-laws)
- Pre-decide what the system can: pick the default value for each differing field and let the user override, not choose every field from scratch. (conservation-of-complexity)
- Say what the merge does to each side, and offer undo after it. (state-coverage)
- Offer "not a duplicate" as a clear third option and say what it changes. (state-coverage, general knowledge)
- Show how many decisions remain, so the user sees progress through the queue. (memory-and-attention-laws)
- An empty queue says nothing is left and what to do next. (state-coverage)

### A long-running search with progress

- Acknowledge the start within 400 ms, then show progress. (familiarity-and-response-time)
- Progress shows steps or counts, not only a spinner. Progress bars make waits tolerable even when inexact. (familiarity-and-response-time, memory-and-attention-laws)
- Show partial results as they arrive if the system has them, and mark the list as still growing. (memory-and-attention-laws, "signs that more content exists")
- Cover all five states, starting, working, finished, stopped early and failed, each answering what happened, how to take it back and what to do next. (state-coverage)
- Let the user stop the search and keep what was found, and say so. (state-coverage)
- If one source fails and others succeed, name the failed source, say the results are partial and offer a retry. (failure-state-design)
- Say what is safe if the user leaves the page, and where the search will be when they come back. (failure-state-design)
- Make the finished state the peak-end moment. Show the count and open the best result first. (memory-and-attention-laws)

### An action with undo (add, skip, remove)

- Every action says what just happened and offers undo in the same place, right after the action. (state-coverage)
- The undo control is close to the action and large enough to hit before it disappears. (hicks-and-fitts-laws)
- Add, skip and remove use one confirm-and-undo pattern on every screen. (cross-screen-consistency)
- Prefer undo over a confirmation dialog for reversible actions. The two-way-door idea says reversible choices need a decision, not a heavy process. (comparing-options)
- Keep the action buttons few and distinct; mark the primary one. (hicks-and-fitts-laws, memory-and-attention-laws)
- Show the new count after the action (for example, 12 added, 3 skipped), so the user sees progress. (memory-and-attention-laws)
- If the action fails, the row returns to its prior state and the message says what to do. (failure-state-design)

### An empty state

- Say why the list is empty (nothing yet, nothing matches, load failed) because each has a different next step. (state-coverage, failure-state-design)
- Give one action that moves the user forward. (failure-state-design)
- Use the same layout and wording pattern for every empty list. (cross-screen-consistency)
- Check it by emptying every list on purpose. (failure-state-design)
- An empty state on first use may point to the first step of the flow and show how far along the user is. (memory-and-attention-laws, general knowledge for the first-use framing)

### An error state

- Say what happened in plain words, what is safe and one action to take. (failure-state-design)
- Do not leave a dead end. "Failed" with no reason and no action is the example the page warns about. (failure-state-design)
- Use one error pattern across the product, with the same placement, wording and retry control. (cross-screen-consistency)
- Say whether the user's input was kept. (failure-state-design, state-coverage)
- Test by switching off the network and by failing each external source in turn. (failure-state-design)
- Treat a handled failure as a chance to build trust, since a well handled failure can leave users as satisfied as no failure. The page's figures are the speaker's citations and were not checked. (failure-state-design)

### A home page

- Show the one thing the user most likely came to do as the distinct action, and keep the other choices few. (hicks-and-fitts-laws, memory-and-attention-laws)
- Show unfinished work first (a search in progress, an import awaiting a decision) with its progress. (memory-and-attention-laws, Zeigarnik)
- Chunk the page into a few groups separated by whitespace. (memory-and-attention-laws, gestalt-principles)
- Cover first-use, nothing-in-progress and load-failed states. (state-coverage)
- Use a familiar layout with the main navigation in the same place as on every other screen, since moving a navigation bar more than doubled time on page in the cited study. (cross-screen-consistency, familiarity-and-response-time)
- Every item on the page earns its place by the value test above. (opportunity-solution-tree, four-product-risks)

### A detail page of one person

- Put the most useful facts first and chunk the rest into labelled groups (identity, place, topics, contact, history). (memory-and-attention-laws, gestalt-principles)
- Mark missing fields as missing and say how to add them, not as a blank. (state-coverage)
- Show where each fact came from, if the product has that information, so the user can judge it. (general knowledge)
- Place the main actions (add to a list, skip, export) near the name, large and distinct, with undo after use. (hicks-and-fitts-laws, memory-and-attention-laws, state-coverage)
- Use the same layout for every person, and the same pattern for a person with little data. (cross-screen-consistency)
- Handle a person that was merged, removed or not found with a clear state and a way back. (failure-state-design)
- Respect the user's time. Load the key facts within 400 ms and show progress for the rest. (familiarity-and-response-time)

### An export

- Say what will be exported (count, columns, which filters apply) before the click. (state-coverage)
- Offer few options and a sensible default. Prefer a format the user already uses. (hicks-and-fitts-laws, familiarity-and-response-time, conservation-of-complexity)
- Show progress for a large export and confirm when the file is ready, with the file name and a next step. (familiarity-and-response-time, state-coverage)
- Handle zero rows, a failed export and a download that was blocked, each with one action. (failure-state-design)
- Say which fields are missing in the file and why, so a blank column is not a surprise. (state-coverage)
- Use the same export pattern wherever an export is offered. (cross-screen-consistency)
- Check the real file, not only the screen that produced it. (general knowledge, in line with the owner's engineering style)

## Whole-product checks

Run these once a flow exists.

- Walk the core flow and ask the three questions at every step (what happened, how to take it back, what next). (state-coverage)
- Break it on purpose. (failure-state-design)
- Use it for an hour and note every spot that does not feel like the same product. (cross-screen-consistency)
- List what a competitor could copy by prompting a tool, and put the effort elsewhere. (commodity-ceiling)
- Test function apart from looks, because a pleasing design can hide problems. (familiarity-and-response-time)

## Caveats

- The statistics on failure-state-design, cross-screen-consistency and commodity-ceiling are the speaker's citations and were not checked, as those pages say.
- The speaker on the Tim Gabe pages runs a design agency. The pages say this.
- The Hick and Fitts constants on hicks-and-fitts-laws are illustrative. Use the laws for direction, not for numbers.
- Palmer and Rock's claim that connection beats every other grouping principle is disputed. (gestalt-principles)
- The Tognazzini counterpoint on conservation-of-complexity says saved effort may be spent again by users doing more. Do not promise that simplification is kept as free time.
