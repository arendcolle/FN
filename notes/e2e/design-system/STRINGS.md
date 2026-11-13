# Which words does each staff page show?

This list holds every user-facing string the new and changed parts introduce, grouped by page, so builders copy them word for word. Numbers and names in it are examples. A placeholder in curly braces, such as `{count}`, is filled by the page. Strings that already ship, such as "Searching…" and "No people found", are listed only where their use changed.

## Every page

- Header links: "Search", "Network"
- List/Map switch links: "List", "Map"
- Map popup, one person: `{name}`, `{role}, {employer}`, `{place}`, "`{n}` new facts" or "1 new fact", "Open profile"; on results, a person not among the shown cards ends with "Show in list" instead
- Map count marker, accessible name: "`{n}` people near `{city}`", or "`{n}` people here" when nobody has a place text
- Map popup, count marker: "`{n}` people near `{city}`" or "`{n}` people here", then per person `{name}`, `{role}, {employer}`, "`{n}` new facts"
- Back link: "Back to the results for “`{question, cut at 60 characters}…`”", "Back to your network", "Back to `{person name}`". No origin known: no back link
- Undo refused (Banner, failed): "This could not be undone, because `{name}` changed since." with "Open profile"
- A missing place: no words on the role line, which ends after the employer

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
- Headings, in order, each followed by its count: "In your network", "Topic and a tie to Flanders or Belgium", "Topic, no known tie", "Tie, topic not confirmed", "Other people found". A search stored before this round: "New"
- Card reason line: "`{reason, from a stored fact}` · `{source short name}`", at most 15 words with the source, for example "Builds 6G channel models at Columbia · columbia.edu"
- Card second line: the tie in words, for example "Studied at Ghent University". Under "Topic, no known tie" the line is left out unless the place is unknown. With no tie under another heading: "No known tie to Flanders". Place words stand only when the role line shows no place: "place unknown". Tie and "place unknown" together: "`{tie in words}` · place unknown"
- Combined line: "Combined from `{n}` records", a link to Sources on the person page
- Same name: "Same name as `{name}` in your network", buttons "Same person", "Add as new", "Skip"
- After Same person: "Added to your network", "· same person as `{name}`", "Undo"
- After Add as new: "Added to your network", "· as a new person", "Undo"
- After Add with a record kept apart: "Added to your network", "·", "1 possible match" (or "`{n}` possible matches"), "Undo"
- Show more: "`{shown}` of `{count}` shown", "Show 20 more", "Show `{n}` more"
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

- Back link, opened from a search: "Back to the results for “`{question, cut at 60 characters}…`”"; from the Network list: "Back to your network"; from another person's page: "Back to `{person name}`"
- Walk line, opened from a search: "`{position}` of `{total}`", "Previous", "Next", joined by " · ". The first person has no Previous, the last no Next
- Head, opened from a search whose card combines records: "Combined from `{n}` records", a link to Sources
- In the network: "In your network since `{d Month yyyy}`" with "Remove from network"
- After Remove from network (Banner): "`{name}` removed from your network." with "Undo"
- Not in the network: "Add", "Skip". With a same-name network person: "Same name as `{name}` in your network", "Same person", "Add as new", "Skip"
- After Add: "Added to your network", "Undo"
- Why block heading: "Why for this search". Lines, each fact once: the card's reason line, the tie in words or "No known tie to Flanders", and "Place unknown" when the head shows no place
- Summary keys: "Studied", "Tie to Flanders" (the tie's organization or place lies in Flanders) or "Tie to Belgium" (any other tie, Brussels and an unknown region included), "Contact". The tie value is the tie in the words of a fact. "Studied" is left out when the tie is that study. Contact value: "`{email}` · `{phone}`", or "Not found"
- Section headings: "Work", "Education", "Ties to Flanders and Belgium", "Places", "Contact", "Sources", "Possible matches"
- Under a section of more than three facts: "Show `{n}` more"
- Fact: "`{relation}` `{organization or place}`, `{years}`", then the source's short name. Years are the fact's own, one span ("2009–2026") or one year ("2015"). Relations, each with an example:
  - "Works at": "Works at Fictional Robotics, 2019–2026"
  - "Worked at": "Worked at Example Health, 2012–2016"
  - "Studied at": "Studied at KU Leuven, 2008–2013"
  - "Fellow of": "Fellow of Belgian American Educational Foundation, 2015"
  - "Member of": "Member of Koninklijke Vlaamse Academie van België voor Wetenschappen en Kunsten, 2021"
  - "Consul for": "Consul for Belgium"
  - "Hosted by": "Hosted by Massachusetts Institute of Technology, 2015"
  - "Named at", for an affiliation a record or a list gives without a job: "Named at Chalmers University of Technology, 2009–2026"
  - "Based in": "Based in Boston, MA" (a home, a base or an office city a source states for the person)
  - "Born in": "Born in Namur, Belgium"
  - "Origin:": "Origin: Belgian"
  - "Topic:": "Topic: AI in health care"
  - "Paper:" with the title and its year: "Paper: Deep learning for sepsis alerts, 2023"
- Joined role: "`{Role}`, `{organization}`, `{years}`", such as "Head of gynecology, UZ Leuven, 2014–2026". A role whose organization comes from another source stands alone: "Chief scientist, 2024"
- List entry: the relation and the list's organization, never the list's title: "Fellow of Belgian American Educational Foundation, 2015"
- Years with gaps, in the proof before the cite: "Years: 2009, 2011–2012, 2019, 2021–2026"
- Folded line, last in Work: "Also named at `{n}` other organizations", source name "OpenAlex record", proof "`{organization}`, `{year}` · `{organization}`, `{year}` · …". No Not correct
- Source name, accessible name: "Source for `{fact}`: `{source short name}`"
- Opened proof: the quote, at most 25 words, then "`{page title}`, `{Month yyyy}` · Original page". No date: "`{page title}` · Original page". A page FN read itself that states no date: "`{page title}`, read `{d Month yyyy}` · Original page". A record: "`{source label}`, `{year}` · Original page"; a url that starts with `fn:`: "`{source label}`, `{d Month yyyy}`"
- Fact: "New", "Not correct". After Not correct: "`{fact}`", "· Removed", "Undo"
- Contact kinds: "Email", "Phone". Empty value: "Not provided". Link: "Edit"
- Contact citations: "From import `{file name}`, row `{n}`, `{d Month yyyy}`", "Entered in FN, `{d Month yyyy}`"
- Contact edit: "Save", "Cancel". After Save: "Saved", "Undo"
- Contact errors: "Enter an email address like name@example.org.", "Enter a phone number with at least 7 digits."
- Sources: "`{source label}`" (two rows with one name add ", `{organization of that record's first Work line}`"), "· `{n}` facts", "· 1 fact" or "· no facts", "Not this person" on every record but the page's own, which comes first. After: "`{source label}` · Separated", "Undo"
- Source labels: a page by its host ("columbia.edu"), a list by its name ("BAEF Belgian Fellows"), a record by its kind ("OpenAlex record", "OpenAlex work", "LinkedIn record", "Import `{file name}`, row `{n}`", "Entered in FN")
- Possible matches note: "These have the same name, but nothing in FN links them to this person for sure."
- Possible match buttons: "Same person", "Different person". After: "Merged into this profile" or "Marked as a different person", with "Undo"

## Source

- Back link: "Back to `{person name}`"
- Title: `{person name}`; opened without a fact: `{source label}`
- Sentence: "The page says: `{fact}`." for a web page; "The page names `{name}`." for a page that only names the person; "The record lists: `{fact}`." for a record, an import or an entry in FN
- Cite line under the sentence: "`{source label}`, `{date}`", the date left out when unknown: "BAEF Belgian Fellows, 2015", "columbia.edu, May 2024", "OpenAlex record, 2025", and the day FN read an undated page: "kslaw.com, read 13 November 2026"
- Passage: about 60 words each side of the quote, "…" at a cut end
- Link: "Open the original page", left out for `fn:` urls
- Disclosure: "Show the stored record"

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
