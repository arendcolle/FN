# Design system and site: how far apart they are

This note compares the FN design system (saved copy: `README.md`, `tokens.json`, `components/bundle.css`, `components/<Name>/README.md` and `preview.html`; written "DS" below) with the CSS, JS and HTML the site ships. It describes today's state only. `fn.css` lines 1 to 154 are the same bytes as `bundle.css`, and 11 more lines are appended after them. `tokens.css` matches `tokens.json` on all 31 tokens and all 14 text styles. The site uses 3 classes the DS lacks (`fn-page`, `fn-debug`, `error`) and 16 DS classes it never emits. Staff pages show no Add, Skip, Undo, Network link or Person link yet. Nothing keeps the copies in step except a one-off restyle commit. Some DS rules are broken, mainly the error pages (they print tracebacks on staff pages) and the 12px map text.

Paths without a prefix are in `src/fn/web/` of this worktree (no uncommitted changes under `src/fn/web`). DS files are cited as `DS:<file>`.

## 1. Is the site CSS the DS CSS?

### fn.css against bundle.css

`diff` of the two files reports only added lines. Nothing in lines 1 to 154 differs, and the first line (a comment, `static/fn.css:1`) is already the same in `DS:components/bundle.css`. There is no extra header. The only difference is this block appended at `static/fn.css:155-165`, which carries its own comment saying these are "candidates to move into the design system" (`static/fn.css:156`).

| fn.css line | Rule | DS has it? |
| --- | --- | --- |
| 157 | `.fn-page` (top rule, page padding) | No |
| 158 | `.fn-debug` (debug page padding) | No |
| 159 | `.fn-switch a` (link styling in the switch) | No (DS styles `.fn-switch button`, `static/fn.css:92`) |
| 160 | `.fn-switch a[aria-current="page"]` (ink fill) | No (DS uses `button[aria-pressed="true"]`, `static/fn.css:93`) |
| 161 | `.fn-map .fn-marker--count { cursor: pointer }` | No |
| 162 | `.fn-marker--count.is-hot` (28px count marker) | No (DS has `.fn-marker--big`, `static/fn.css:98`, for single dots only) |
| 163 | `.maplibregl-popup-content { max-height: 30vh; overflow-y: auto }` | No (DS sets radius and padding at `static/fn.css:101`) |
| 164 | `.fn-popup__role + .fn-popup__name` (gap between people) | No |
| 165 | `.fn-source__text mark { scroll-margin-top: 30vh }` | No (DS rule is `static/fn.css:125`) |

### tokens.css against tokens.json

`tokens.css` line 1 says it is "Generated from the FN design system's tokens.json" (`static/tokens.css:1`). A script comparison found no difference:

- 14 colour tokens, 9 spacing tokens, 3 radius tokens and 5 layout tokens match `DS:tokens.json` value for value (`static/tokens.css:15-45`). `--on-ink` is `var(--ground)`, as `{ground}` in the JSON (`static/tokens.css:18`).
- The 3 font family strings match (`static/tokens.css:46-48`).
- All 14 `text-*` classes match size, line height, weight, family and letter spacing (`static/tokens.css:51-64`).
- `tokens.css` has no variable that `tokens.json` lacks.
- The two `unicode-range` strings in the DS README appear verbatim in `tokens.css`. It has 10 `@font-face` rules (`static/tokens.css:3-12`) for the 10 woff2 files, and the sha256 of all 10 files in `static/fonts/` equals the DS README table. `tokens.json` itself lists only the 5 latin files; the 5 latin-ext files come from the README.
- Three OFL licence files sit in `static/fonts/` next to the fonts.

## 2. Classes: site against DS

I took every class the site writes in `class_=`, `body_class`, `className`, `classList` and `querySelector` calls in `app.py`, `html.py` and `static/map.js`, and every class selector in `bundle.css` and `tokens.css`.

### Used by the site but not defined by the DS

| Class | Where | What it does |
| --- | --- | --- |
| `fn-page` | `app.py:78`, `app.py:161-162` | Wrapper with a top rule and padding on the error pages and the Recent searches section (`static/fn.css:157`). |
| `fn-debug` | `html.py:117` | Body class on every debug page (`static/fn.css:158`). |
| `error` | `app.py:284` | Chip edit error on the debug page. No CSS defines it, so the message is unstyled. |

### Defined by the DS and used by the site

`fn-app` (`app.py:438`, through `body_class`), `fn-header`, `fn-logo`, `fn-nav` (`html.py:111-115`), `fn-search`, `fn-search__field`, `fn-input`, `fn-error` (`app.py:136-143`), `fn-btn`, `fn-btn--dark` (`app.py:142`, `app.py:404`), `fn-section` (`app.py:161`, `app.py:381`), `fn-card`, `fn-card__name`, `fn-card__role`, `fn-card__ties` (`app.py:373-378`), `is-hot` (`static/map.js:43`, `static/map.js:50`), `fn-quote`, `fn-quote__cite` (`app.py:352-353`), `fn-status`, `fn-status__bar` (`app.py:424`), `fn-notice`, `fn-notice--failed`, `fn-notice__title` (`app.py:400-411`), `fn-recent`, `fn-recent__meta`, `fn-recent__meta--running`, `fn-recent__meta--failed` (`app.py:149-161`), `fn-results`, `fn-results--no-map`, `fn-results__list` (`app.py:431-434`), `fn-switch` (`app.py:430`), `fn-map` (`app.py:432`), `fn-marker`, `fn-marker--count` (`static/map.js:112`), `fn-popup__name`, `fn-popup__role` (`static/map.js:69`, `static/map.js:72`), `fn-source`, `fn-source__title`, `fn-source__url`, `fn-source__text` (`app.py:610-613`), and all 14 `text-*` classes.

`maplibregl-popup-content` is a MapLibre class the DS restyles (`static/fn.css:101`). The site gets it from MapLibre, not from its own HTML.

### Defined by the DS and never used by the site

| Class | DS part | Why unused today |
| --- | --- | --- |
| `fn-btn--add` | Button | No Add action exists (no route besides search, rerun and read pages). |
| `fn-btn--quiet` | Button | No Skip action. |
| `fn-link` | Button | No Undo. |
| `fn-card__acts` | PersonCard | Cards have no buttons (`app.py:373-379`). |
| `fn-done` | PersonCard | No "Added to your network" state. |
| `fn-card--skipped`, `fn-skipline` | PersonCard | No Skipped state. |
| `fn-claim`, `fn-claim__what` | Claim | No Person page. |
| `fn-row`, `fn-row__name`, `fn-row__role`, `fn-row__ties`, `fn-row__meta` | NetworkRow | No Network page. |
| `fn-marker--big` | MapMarker | The site grows a single dot with MapLibre feature state (`static/map.js:44`) and a count marker with `.is-hot` (`static/fn.css:162`). |
| `fn-popup` | MapMarker | The site's popup is MapLibre's own box; only the two inner span classes are used (`static/map.js:65-78`). |

The DS has a `Cover` preview (`DS:components/Cover/preview.html`) with no README and no classes of its own in `bundle.css`. It is DS decoration, not a site part.

## 3. Components: use on staff pages and markup match

"Match" means the site's tags and classes equal the DS `preview.html` for the same part.

| Part | On a staff page today? | Match with preview |
| --- | --- | --- |
| Button | Dark only: Search on Ask and results pages (`app.py:142`), Try again on the stopped notice (`app.py:404`). | Same classes (`fn-btn fn-btn--dark text-control`). Add, Quiet and Link are never emitted. |
| Claim | No page. A Person page does not exist. | n/a |
| Header | Every staff page (`html.py:111-116`). | Different. Site has one link, Search. DS preview and README have two, Search and Network. Network has no route. |
| MapMarker | Results page, `static/map.js`. | Mostly. Paint values match: radius 7 and 10, stroke 2, accent fill, raised stroke (`static/map.js:104-106`). Count marker is `span.fn-marker.fn-marker--count.text-label` as in the preview (`static/map.js:112`). Differs: hover size on count markers uses `.is-hot` and a site-only rule (`static/fn.css:162`) instead of `fn-marker--big`; the narrow-screen popup is MapLibre's box with no `.fn-popup` wrapper (`static/map.js:78`). Fit padding 64 and max zoom 11 match (`static/map.js:35`). |
| NetworkRow | No page. | n/a |
| Notice | Results page when the search stopped or found nobody (`app.py:395-412`). | Same structure and classes. Site wraps the Try again button in a `form` posting the question (`app.py:403-405`). Sentence text differs from the preview's example by design. |
| PersonCard | Results page (`app.py:369-379`). | Partly. Site emits `article.fn-card[data-person]`, name `h3`, role `p`, ties `p`, quote. Differences: the name is plain text, not a link to a Person page (`app.py:374`; preview has `<a>`); no `fn-card__acts` with Add and Skip; no Added or Skipped states; `data-person` is site-only, used by `static/map.js:25`. Ties line shows at most three organizations then "+N more" (`app.py:317-323`), as specified. "location not found" is written when no place exists (`app.py:371`). |
| Quote | Inside every card (`app.py:345-354`). | Same tags and classes. The site uses curly marks, as the preview does. |
| RecentSearches | Ask page (`app.py:156-163`). | Same `h2.fn-section` and `ul.fn-recent > li > a + span`. The site wraps them in `section.fn-page`, which the preview lacks and the DS CSS does not define. |
| ResultsLayout | Results page (`app.py:429-435`). | Order matches (switch, list, map). The switch element differs, see ViewSwitch. `fn-app` is on `body` (`app.py:438`). |
| SearchBox | Ask and results pages (`app.py:132-144`). | Same tags, classes, `aria-invalid` and `aria-describedby`. The form carries `method="post" action="/searches"`. Rows are 1, or 3 when the question is over 80 characters (`app.py:136`). |
| SectionHeading | Results page, with the counts (`app.py:381`), and "Recent searches" (`app.py:161`). | Same: `h2.fn-section.text-label` plus a `span` with the count. |
| SourceText | Source page (`app.py:604-615`). | Same tags and classes (`div.fn-source > h1, p, pre > mark#quote`). |
| StatusLine | Results page while queued or running (`app.py:424`). | Identical markup. It shows only "Searching…", with no count, which the DS README allows "until live updates exist". |
| Table | Debug pages only (`app.py:473-523`, `html.py:77-82`). | Bare `table`, `th`, `td`, `pre`, as the DS says. |
| ViewSwitch | Results page (`app.py:427-430`). | Different. DS: `div.fn-switch[role=group]` with two `button[aria-pressed]`. Site: `nav.fn-switch[aria-label=View]` with two `a[href][data-view][aria-current=page]`, and `/searches/{id}/map` is a separate route (`app.py:702-704`). `static/map.js:7-15` flips `data-view` and `aria-current`, not `aria-pressed`. The DS `.fn-switch button` rules (`static/fn.css:92-93`) match nothing on the site. |

## 4. DS written rules checked against the site

Rules that hold are not repeated. Rules about Add, Skip, Added, Undo, network and Person pages cannot be broken yet because those parts do not exist.

### Rules the site breaks

| Rule (quoted from `DS:README.md` or a part README) | Breaking code |
| --- | --- |
| "FN's pipeline stays out of staff pages … exception names and tracebacks" and Notice: "Staff never see technical details: no exception names, tracebacks or step names." | A 500 renders `error_page("Server error", error)` with the full redacted traceback inside the staff header and `fn-page` (`app.py:832`, `app.py:78`). A test requires it (`tests/test_web.py:376-384`). |
| "Say what happened and what to do next." | The 404 and 403 pages show only a status code or "Refused" with one raw sentence, and no next step (`app.py:78`, `app.py:92`, `app.py:817`). The 404 title is the number, for example "404". |
| "Nothing staff read is under 13px." | The MapLibre map font is 12px (`.maplibregl-map{font:12px/20px …}` in `static/maplibre-gl.css`, minified on one line). The compact attribution (`static/map.js:23`) and zoom control inherit it. No `fn.css` rule changes it. |
| "Every control shows a 2px solid ink focus ring" | Count markers are clickable `div`s with no `tabindex` or role, so keyboard users cannot reach them (`static/map.js:109-117`). Single dots are canvas features (`static/map.js:104`). |
| Header: "shows FN and the two staff links, Search and Network, on every staff page." | One link only (`html.py:113`). |
| PersonCard: name is "a link to the Person page". | Name is plain text (`app.py:374`). |
| ViewSwitch: "`aria-pressed` on the two buttons" and "`map.js` flips `data-view` and `aria-pressed`." | Links with `aria-current`; `static/map.js:12` sets `aria-current`. |
| README Spacing: "every padding in `bundle.css` uses [space tokens]". | `.fn-source__text mark` uses `padding: 0 2px` (`static/fn.css:125`). This line is also in `bundle.css`, so the DS breaks its own rule. |
| README Type: "`bundle.css` never sets font size, line height, weight or family, except … `body`, `th`, `td` and `pre`". | `.fn-link { font: inherit }` (`static/fn.css:42`) and `.fn-quote__cite { font-style: normal }` (`static/fn.css:64`). Both are in `bundle.css` too. |
| "The only output is people with evidence." / "ranks". | `/api/searches/{id}/geo` returns `rank`, `section`, `date_method`, `quote` and `source_page` for every dot (`app.py:462-467`). `static/map.js` shows none of them, but the browser fetches them (`static/map.js:86`). |

### Rules the site follows (checked)

- No `/debug` link on a staff page: `html.py:111-116` has none, and a test checks it (`tests/test_web.py:202-218`).
- Voice: no exclamation mark, "please" or "successfully" in `app.py`. Recent-search dates are words (`app.py:121-129`). Counts such as "5 people · today" (`app.py:152`).
- Quote: upright, quote marks added, inner double quotes turned single, cut at 240 characters with "…" (`app.py:347-350`). Dates as words or "date unknown" (`app.py:334-342`).
- Colour: `accent` appears only at `static/fn.css:38`, `51`, `58`, `97`. No gradients. Shadows only on the picked card ring (`static/fn.css:51`), the marker ring (`static/fn.css:97`), the DS popup (`static/fn.css:100`, unused) and MapLibre's own popup shadow.
- States: failed shows "This search stopped" plus Try again; empty shows "No people found" and the count of sources read (`app.py:395-412`); the map is hidden through `fn-results--no-map` (`app.py:434`); the form error sits under the field (`app.py:139`); no Recent searches section when none exist (`app.py:161-162`).
- Focus and current page: `:focus-visible` rule at `static/fn.css:12`; `aria-current="page"` on the nav link (`html.py:113`); `aria-current="true"` on the picked card (`static/map.js:61`).
- Motion: only the bar animation and the 120 ms border change (`static/fn.css:49`, `70`); reduced motion stops the bar (`static/fn.css:72`) and uses instant scroll (`static/map.js:62`).
- Layout: gutters (`static/fn.css:3`, `143`), 900px breakpoint in CSS and in `matchMedia` (`static/map.js:3`), `fn-app` on `body` (`app.py:438`), `fn-results--no-map` list width (`static/fn.css:139`).
- Fonts are served from `/static`, no CDN. The CSP is `default-src 'self'` (`app.py:57-60`).
- Recent searches newest first: `ORDER BY created_at DESC` (`src/fn/store.py:115`).

## 5. How the site CSS is kept in step

Nothing keeps it in step today.

- There is no script that copies or generates `tokens.css` from `tokens.json`, or `fn.css` from `bundle.css`. `scripts/` holds `gold`, `seeds` and `vendor_map.py` only.
- The only link is a comment: `tokens.css` says it was generated from the DS tokens (`static/tokens.css:1`). `fn.css:1` names no source, and `fn.css:156` says the appended block is a set of candidates to move into the DS.
- The CSS was copied once, in commit `cc82115` ("Style the staff pages with the FN design system", 2026-11-05). `git log` shows no later change to `fn.css` or `tokens.css`.
- No test compares the site with the DS. `tests/test_web.py:308` only checks that `/static/fn.css` returns 200. Tests assert some class names and strings, for example `fn-card`, `text-year`, `fn-results--no-map` (`tests/test_web.py:259-296`).
- The repo's `notes/` folder has no sync note. The restyle plan and brief (`plan.md`, `restyle-brief.md`) are untracked files in the main checkout's `notes/design/`, not in this worktree. They assign "tokens.css generated from tokens.json" and "fn.css built from bundle.css" to a "Restyle session" (`notes/design/plan.md:125-127` in the main checkout).
- `notes/mvp0/architecture.md:92` lists `fn.css` among the static files and does not mention the DS.

## 6. Vocabulary a designer has

Names only, from `tokens.json` and `static/tokens.css`.

- Colour tokens (14): `ground`, `raised`, `ink`, `on-ink`, `muted`, `rule`, `rule-strong`, `field`, `accent`, `on-accent`, `running`, `running-track`, `failed`, `map-ground`.
- Spacing tokens (9): `space-1`, `space-2`, `space-3`, `space-4`, `space-5`, `space-6`, `space-7`, `space-8`, `space-12`. There is no `space-9`, `space-10` or `space-11`.
- Radius tokens (3): `radius-sm`, `radius-md`, `radius-lg`.
- Layout tokens (5): `list-width`, `search-width`, `notice-width`, `narrow-list-width`, `measure`. The site also defines `--fn-gutter` (`static/fn.css:3`, `143`).
- Font families (3): `--font-serif` (Source Serif 4), `--font-sans` (IBM Plex Sans), `--font-mono` (IBM Plex Mono).
- Serif styles: `text-logo`, `text-name`, `text-title`, `text-quote`, `text-popup`.
- Sans styles: `text-body`, `text-strong`, `text-control`, `text-switch`, `text-meta`, `text-meta-strong`, `text-small`, `text-label`.
- Mono style: `text-year`.
- Component classes in `bundle.css`: `fn-header`, `fn-logo`, `fn-nav`, `fn-search`, `fn-search__field`, `fn-input`, `fn-error`, `fn-btn` (`--add`, `--dark`, `--quiet`), `fn-link`, `fn-section`, `fn-card` (`__name`, `__role`, `__ties`, `__acts`, `--skipped`), `fn-done`, `fn-skipline`, `fn-quote` (`__cite`), `fn-status` (`__bar`), `fn-notice` (`__title`, `--failed`), `fn-recent` (`__meta`, `--running`, `--failed`), `fn-switch`, `fn-map`, `fn-marker` (`--big`, `--count`), `fn-popup` (`__name`, `__role`), `fn-claim` (`__what`), `fn-row` (`__name`, `__role`, `__ties`, `__meta`), `fn-source` (`__title`, `__url`, `__text`), `fn-results` (`__list`, `--no-map`), `fn-app`, and the state class `is-hot`.
- States by attribute: `aria-current="page"` (nav, switch), `aria-current="true"` (picked card), `aria-invalid="true"` (field), `aria-pressed` (DS switch buttons), `data-view="list|map"`.
- Breakpoint: 900px, hard-coded in `bundle.css` (`static/fn.css:132`, `142`).
