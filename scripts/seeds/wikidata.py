# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx"]
# ///
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

LIST = "wikidata"
ENDPOINTS = ["https://query.wikidata.org/sparql?format=json&", "https://qlever.dev/api/wikidata?"]
ITEM = "http://www.wikidata.org/entity/"
LANGS = ("en", "nl", "fr")
US, BE = ITEM + "Q30", ITEM + "Q31"
DATE_METHOD = "item modified"
VARS = ["p", "kind", "v", "vLabel", "lang", "country", "start", "end", "city", "cityLabel", "stateLabel"]
PREFIXES = """PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/> PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/> PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> PREFIX schema: <http://schema.org/>
"""
# Living humans educated at or employed by a Belgian organization, with a US employer or a US residence.
PEOPLE = PREFIXES + """SELECT DISTINCT ?p WHERE {
  ?p wdt:P31 wd:Q5 . { ?p wdt:P69 ?be } UNION { ?p wdt:P108 ?be } ?be wdt:P17 wd:Q31 .
  { ?p wdt:P108 ?us . ?us wdt:P17 wd:Q30 } UNION { ?p wdt:P551 ?home . ?home wdt:P17 wd:Q30 }
  FILTER NOT EXISTS { ?p wdt:P570 ?died } }"""
LABEL = '?{0} rdfs:label ?{0}Label FILTER(LANG(?{0}Label) = "en")'
STATE = "?{0} wdt:P131|wdt:P131/wdt:P131|wdt:P131/wdt:P131/wdt:P131 ?state . ?state wdt:P31 wd:Q35657 . " + LABEL.format("state")
DATES = "OPTIONAL { ?st pq:P580 ?start } OPTIONAL { ?st pq:P582 ?end }"
STATEMENT = "?p p:{0} ?st . ?st ps:{0} ?v . ?st wikibase:rank ?rank FILTER(?rank != wikibase:DeprecatedRank)"
BRANCHES = {
    "label": '?p rdfs:label ?v BIND(LANG(?v) AS ?lang) FILTER(?lang IN ("en", "nl", "fr"))',
    "description": '?p schema:description ?v FILTER(LANG(?v) = "en")',
    "modified": "?p schema:dateModified ?v",
    "occupation": "?p wdt:P106 ?v . " + LABEL.format("v"),
    "field": "?p wdt:P101 ?v . " + LABEL.format("v"),
    "school": f"{STATEMENT.format('P69')} ?v wdt:P17 wd:Q31 . {LABEL.format('v')} {DATES}",
    "employer": f"""{STATEMENT.format('P108')} {LABEL.format('v')} {DATES}
  OPTIONAL {{ ?v wdt:P17 ?country FILTER(?country IN (wd:Q30, wd:Q31)) }}
  OPTIONAL {{ ?v wdt:P159 ?city . ?city wdt:P17 wd:Q30 . {LABEL.format('city')} OPTIONAL {{ {STATE.format('city')} }} }}""",
    "residence": f"{STATEMENT.format('P551')} ?v wdt:P17 wd:Q30 . {LABEL.format('v')} {DATES} OPTIONAL {{ {STATE.format('v')} }}",
}
FACTS = PREFIXES + "SELECT " + " ".join("?" + v for v in VARS) + " WHERE { VALUES ?p { {qids} }\n" + "\nUNION ".join(
    f'{{ {branch} BIND("{kind}" AS ?kind) }}' for kind, branch in BRANCHES.items()) + " }"
# The facts of all people in one query time out on both endpoints; a page of people answers in seconds.
PAGE = 150
SKIPS = ("no label in en, nl or fr", "label is only the item id", "employer statement ended",
         "employer statement without a start date", "no current US employer or US residence",
         "no Belgian school or current Belgian employer")


class StructureError(Exception):
    pass


def ask(query: str) -> dict:
    """The JSON answer of the first endpoint that answers; one that answers is asked first from then on.

    Raises RuntimeError when no endpoint answers, such as on a 429 or a timeout from each.
    """
    errors = []
    for endpoint in list(ENDPOINTS):
        try:
            answer = common.fetch(endpoint + urlencode({"query": query})).json()
        except (httpx.HTTPStatusError, httpx.TransportError, ValueError) as err:
            errors.append(f"{endpoint.split('?')[0]}: {type(err).__name__} {str(err)[:120]}")
            continue
        ENDPOINTS.insert(0, ENDPOINTS.pop(ENDPOINTS.index(endpoint)))
        return answer
    raise RuntimeError("no query endpoint answered: " + "; ".join(errors))


def bindings(answer: dict, columns: list[str]) -> list[dict]:
    """The answer's bindings flattened to their values; raises StructureError when the columns or rows are off."""
    head = answer.get("head", {}) if isinstance(answer, dict) else {}
    if head.get("vars") != columns:
        raise StructureError(f"answer columns changed: {head.get('vars')}")
    found = answer.get("results", {}).get("bindings")
    if not isinstance(found, list) or not found:
        raise StructureError("answer has no bindings")
    return [{k: b.get("value") for k, b in binding.items()} for binding in found]


def people_of(answer: dict) -> list[str]:
    """The item ids of the people query's answer."""
    found = [b.get("p", "") for b in bindings(answer, ["p"])]
    if not all(p.startswith(ITEM + "Q") for p in found):
        raise StructureError("people answer holds a value that is no item")
    return [p.removeprefix(ITEM) for p in found]


def group(answers: list[dict]) -> dict[str, list[dict]]:
    """The facts of the fact answers by item id; raises StructureError on a changed shape."""
    people: dict[str, list[dict]] = {}
    for answer in answers:
        for fact in bindings(answer, VARS):
            if fact.get("kind") not in BRANCHES or not str(fact.get("p", "")).startswith(ITEM) or not fact.get("v"):
                raise StructureError(f"unexpected fact: {fact}")
            people.setdefault(fact["p"].removeprefix(ITEM), []).append(fact)
    return people


def facts_query(qids: list[str]) -> str:
    return FACTS.replace("{qids}", " ".join(f"wd:{q}" for q in qids))


def year(value: str | None) -> str:
    """The year of a date value; 'unknown' for Wikidata's unknown value."""
    return "" if not value else value[:4] if value[:4].isdigit() else "unknown"


def dates(fact: dict) -> str:
    """A statement's dates as words, such as ' (from 2015)' or ' (2001 to 2005)'."""
    start, end = year(fact.get("start")), year(fact.get("end"))
    if start and end:
        return f" ({start} to {end})"
    return f" (from {start})" if start else f" (until {end})" if end else ""


def place_of(fact: dict, city_key: str) -> str | None:
    """The city a fact names, as 'City, State' when the state is known."""
    city = fact.get(city_key)
    if not city:
        return None
    state = fact.get("stateLabel")
    return f"{city}, {state}" if state and state != city else city


def unique(facts: list[dict], kind: str) -> list[dict]:
    """The facts of one kind, one per value and dates, the state with the shortest label first."""
    seen: dict[tuple, dict] = {}
    for fact in sorted((f for f in facts if f["kind"] == kind), key=lambda f: len(f.get("stateLabel") or "")):
        seen.setdefault((fact["v"], fact.get("start"), fact.get("end"), fact.get("country")), fact)
    return list(seen.values())


def person_row(qid: str, facts: list[dict], skips: Counter) -> tuple[dict, str] | None:
    """One person's row without its raw fields, and its text layer; None, counted in skips, when left out."""
    labels = {f["lang"]: f["v"] for f in facts if f["kind"] == "label"}
    name = next((common.norm(labels[lang]) for lang in LANGS if labels.get(lang)), None)
    if not name:
        skips[SKIPS[0]] += 1
        return None
    if name == qid:
        skips[SKIPS[1]] += 1
        return None
    employers, us_jobs, be_jobs = unique(facts, "employer"), [], []
    for job in employers:
        if job.get("country") not in (US, BE):
            continue
        if job.get("end"):
            skips[SKIPS[2]] += 1
        elif not job.get("start"):
            skips[SKIPS[3]] += 1
        else:
            (us_jobs if job["country"] == US else be_jobs).append(job)
    us_jobs.sort(key=lambda j: j["start"], reverse=True)
    # An employer in both countries counts as a US employer only.
    be_jobs = [j for j in be_jobs if j["v"] not in {u["v"] for u in us_jobs}]
    homes = [f for f in unique(facts, "residence") if not f.get("end")]
    if not us_jobs and not homes:
        skips[SKIPS[4]] += 1
        return None
    schools = unique(facts, "school")
    if not schools and not be_jobs:
        skips[SKIPS[5]] += 1
        return None
    occupations = sorted({f["vLabel"] for f in facts if f["kind"] == "occupation" and f.get("vLabel")})
    fields = sorted({f["vLabel"] for f in facts if f["kind"] == "field" and f.get("vLabel")})
    description = next((f["v"] for f in facts if f["kind"] == "description"), None)
    modified = max((f["v"][:10] for f in facts if f["kind"] == "modified"), default=None)
    if not modified:
        raise StructureError(f"{qid} has no change date")
    place = next((p for p in [place_of(h, "vLabel") for h in homes] + [place_of(j, "cityLabel") for j in us_jobs] if p),
                 None)
    lines = [name] + ([description] if description else [])
    lines += [f"occupation: {occupations[0]}"] if occupations else []
    lines += [f"field of work: {f}" for f in fields]
    lines += [f"educated at: {s['vLabel']}{dates(s)}" for s in schools]
    lines += [f"employer: {j['vLabel']}{dates(j)}" + (f", headquarters {place_of(j, 'cityLabel')}" if j.get("cityLabel") else "")
              for j in us_jobs + be_jobs]
    lines += [f"residence: {place_of(h, 'vLabel')}{dates(h)}" for h in homes]
    lines.append(f"last changed: {modified}")
    url = ITEM + qid
    # One relation per institution: the loader keys a claim on its value and quote, not its relation.
    names: dict[str, str] = {}
    for inst, relation in [(j, "employer") for j in us_jobs] + [(s, "student") for s in schools] + [(j, "home") for j in be_jobs]:
        names.setdefault(inst["vLabel"], relation)
    row = {
        "list": LIST, "row_key": common.row_key(LIST, name, None, qid), "name": name, "name_on_page": name,
        "year": None, "role": occupations[0] if occupations else None,
        "institutions": [{"name": n, "relation": r} for n, r in names.items()],
        "field": ", ".join(fields) or description, "place": place, "jurisdiction": None, "profile_url": url,
        "source_url": url, "source_title": f"Wikidata item {name}", "source_date": modified,
        "date_method": DATE_METHOD, "page": None,
    }
    return row, "\n".join(lines)


def build_rows(people: dict[str, list[dict]], save, fetched: str) -> tuple[list[dict], Counter]:
    """Rows for every person kept, each quoting the text layer save(qid, facts, text) stored; and the skip counts."""
    rows, skips = [], Counter()
    for qid, facts in sorted(people.items(), key=lambda item: int(item[0].lstrip("Q"))):
        built = person_row(qid, facts, skips)
        if built:
            row, text = built
            rows.append(row | {"quote": common.norm(text), "raw_path": save(qid, facts, text), "fetched_at": fetched})
    return rows, skips


def save(qid: str, facts: list[dict], text: str) -> str:
    return common.save_raw(LIST, f"{qid}.json", json.dumps(facts, ensure_ascii=False, indent=1).encode(), text)


def main() -> None:
    qids = people_of(ask(PEOPLE))
    people = group([ask(facts_query(qids[i:i + PAGE])) for i in range(0, len(qids), PAGE)])
    rows, skips = build_rows(people, save, date.today().isoformat())
    out = common.write_rows(LIST, rows)
    print(f"{len(qids)} people in the answer; wrote {len(rows)} rows to {out}")
    for reason in SKIPS:
        print(f"left out, {reason}: {skips[reason]}")


if __name__ == "__main__":
    try:
        main()
    except (StructureError, ValueError, RuntimeError) as err:
        print(f"wikidata: {err}", file=sys.stderr)
        sys.exit(1)
