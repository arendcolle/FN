# Which words does each staff page show?

This list holds every user-facing string the new and changed parts introduce, grouped by page, so builders copy them word for word. Numbers and names in it are examples. A placeholder in curly braces, such as `{count}`, is filled by the page. Strings that already ship, such as "Searching…" and "No people found", are listed only where their use changed.

## Every page

- Header links: "Search", "Network"
- List/Map switch links: "List", "Map"
- Map popup, one person: `{name}`, `{role}, {employer}`, `{place}`, "`{n}` new facts" or "1 new fact", "Open profile"
- Map popup, shared dot: "`{n}` people here", then per person `{name}`, `{role}, {employer}`, "`{n}` new facts"
- Undo refused (Banner, failed): "This could not be undone, because `{name}` changed since." with "Open profile"
- A missing place: "location not found"

## Home

- Recent searches heading: "Recent searches"
- Link under the three newest: "All searches"
- Network heading: "In your network", with the link "Import"
- Filter box placeholder: "Name, place or organization". Its accessible name: "Filter your network". Button: "Filter"
- Count line: "`{count}` people · `{n}` not on the map · Export", or "`{count}` people · Export" when everyone is on the map. "Export" is a link
- Network row: "Added `{d Mon yyyy}`", "`{n}` new facts", "1 new fact"
- Show more: "`{shown}` of `{count}` shown", "Show `{n}` more"
- Empty network notice: title "Your network is empty", text "Import a CSV file of people you already know, or search above and add people from the results.", button "Import"

## All searches

- Heading: "All searches `{count}`"
- Row meta, as on Home: "`{n}` people · `{when}`", "Searching…", "Failed"

## Results

- Count line: "`{count}` people · `{n}` not on the map · Export", with "Export" as a link. Left out while the search runs
- Status line while running: "Searching…", "Searching… 1 person so far", "Searching… `{n}` people so far"
- Done with a source that could not be read: "Some sources could not be read, so this list may be incomplete." and the button "Search again"
- Stopped after finding people: "This search stopped before it finished." and the button "Run again"
- Stopped before finding anyone (Notice): title "This search stopped", text "FN ran into a problem before it found anyone. Your question is kept, so Try again runs it once more.", button "Try again"
- Card evidence from a record: "`{relation}` `{organization}`, `{years}`" with the citation "`{source label}`, `{date}`", for example "Studied at KU Leuven, 2012–2017" and "OpenAlex record, 2025"
- Same name: "Same name as `{name}` in your network", buttons "Same person", "Add as new", "Skip"
- After Same person: "Added to your network", "· same person as `{name}`", "Undo"
- After Add as new: "Added to your network", "· as a new person", "Undo"
- After Add with a record kept apart: "Added to your network", "·", "1 possible match" (or "`{n}` possible matches"), "Undo"
- Show more: "`{shown}` of `{count}` shown", "Show 50 more", "Show `{n}` more"
- Skipped people: "`{n}` skipped people hidden" with "Show", "`{n}` skipped people shown" with "Hide", "1 skipped person hidden"

## Network

- Heading link: "Import"
- Filter tokens: "In `{place}`", "From import `{file name}`", "New facts only", each with "Clear". Accessible name of each Clear: "Clear `{token text}`"
- Count line without a filter: "`{count}` people · `{n}` not on the map · Export"
- Count line with a filter active: "`{count}` people · `{n}` not on the map · Export these `{count}`" and "Clear all" at the right
- With 0 people there is no export link
- No matches: count line "0 people" and "Clear all". Notice title "Nobody matches". Text, by filter:
  - Text only: "Nobody in your network has “`{text}`” in their name, place or organization. Check the spelling, or use Clear all to see all `{total}` people."
  - Text and an import token: "Nobody from import `{file name}` has “`{text}`” in their name, place or organization. Check the spelling, clear the import filter, or use Clear all to see all `{total}` people."
- Empty network notice: as on Home, with the text "Import a CSV file of people you already know, or run a search and add people from the results." where "run a search" links to Home
- After an import (Banner): "`{n}` people imported from `{file name}`." with "Show them"

## Person

- Back link, when reached from a result: "Back to the results for “`{question, cut at 60 characters}…`”"
- In the network: "In your network since `{d Month yyyy}`" with "Remove"
- After Remove (Banner): "`{name}` removed from your network." with "Undo"
- Not in the network: "Add", "Skip". With a same-name network person: "Same name as `{name}` in your network", "Same person", "Add as new", "Skip"
- After Add: "Added to your network", "Undo"
- Group headings: "Contact", "Ties to Belgium", "Work", "Places", "Found as", "Possible matches"
- Contact kinds: "Email", "Phone". Empty value: "Not provided". Link: "Edit"
- Contact citations: "From import `{file name}`, row `{n}`, `{d Month yyyy}`", "Entered in FN, `{d Month yyyy}`"
- Contact edit: "Save", "Cancel". After Save: "Saved", "Undo"
- Contact errors: "Enter an email address like name@example.org.", "Enter a phone number with at least 7 digits."
- Fact: "New", "Remove". After Remove: "`{fact}`", "· Removed", "Undo"
- Found as: "`{source label}`", "· `{n}` facts" or "· 1 fact", "Not this person". After: "`{source label}` · Separated", "Undo"
- Source labels: "OpenAlex record", "LinkedIn record", "Import `{file name}`, row `{n}`", "Entered in FN", or the site's host name
- Possible matches note: "These have the same name, but nothing in FN ties them to this person for sure."
- Possible match buttons: "Same person", "Different person". After: "Merged into this profile" or "Marked as a different person", with "Undo"

## Import

- Title: "Import people"
- Lead: "Upload a CSV file with one person per row. FN shows you what it will do before anything is imported."
- Field label: "CSV file". Hint: "The first row holds the column names. Commas and semicolons both work." Button: "Upload"
- Columns heading: "Columns FN reads"
- Columns note: "Name your columns like this, in any order. FN ignores other columns, and a blank cell changes nothing for someone already in your network."
- Table headers: "Column", "Required", "What FN does with it". Values "Yes", "No"
- Column descriptions:
  - name: "The person's full name."
  - email: "A contact detail. FN also recognizes the person by it in a later import."
  - phone: "A contact detail."
  - organization: "Where the person works."
  - role: "The person's job title."
  - city: "With state and country, puts the person on the map."
  - state: "The US state, or the province or region elsewhere."
  - country: "The country of the city."
  - linkedin_url: "The address of their LinkedIn profile. FN recognizes the person by it in later imports and searches."
  - orcid: "Their ORCID iD. FN recognizes the person by it in later imports and searches."
- Upload errors, under the field:
  - "Choose a CSV file to upload."
  - "`{file name}` is not a CSV file. In Excel, use Save as and pick CSV."
  - "`{file name}` has no name column. Rename the column that holds names to name and upload it again."
  - "`{file name}` has no rows under the column names."
- After Discard (Banner): "`{file name}` discarded. Nothing was imported."

## Import preview

- Title: "Check `{file name}`"
- Lead: "Nothing is imported until you press Import `{n}` people."
- Counts, a count of 0 left out: "`{n}` new people", "`{n}` already in your network", "`{n}` with the same name as someone in your network", "`{n}` rows skipped" or "1 row skipped"
- Note: "FN adds what is new in the `{n}` rows already in your network to their profiles."
- Skipped row reasons: "Row `{n}` has no name, so FN skips it."
- Ignored columns: "FN ignores `{n}` columns: `{names}`." or "FN ignores 1 column: `{name}`."
- Name matches heading: "Same name as someone in your network"
- Name matches note: "Tick a row only if it is the same person. An unticked row becomes a new person, and you can still merge it later from the profile."
- Header box: "All of these are the same person"
- Row box: "Row `{n}`. Same as `{name}`?"
- Row facts: "In the file: `{role}, {organization} · {place} · {email}`", "In your network: `{role}, {employer} · {place}` · added `{d Month yyyy}`"
- Buttons: "Import `{n}` people", "Discard"
- Under the buttons: "You can remove anyone later from their profile."
- Rows heading: "Rows in `{file name}` `{count}`"
- Table "What happens" values: "New", "In your network", "Same name", "Skipped: no name"
- Nothing to import: "Every row in `{file name}` is already in your network, and nothing in it is new." with "Discard" only
- Checkbox error: "`{name}` left your network since this preview. Leave this box empty to import the row as a new person."
