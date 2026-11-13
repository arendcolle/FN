"""Ask a web researcher for people, one call per search angle, and merge its leads into one list of people with pages."""
from urllib.parse import urldefrag, urlsplit

from fn import parse
from fn.contracts import Chips, Considered, ScoutLead, ScoutLeads, clean_name, name_key
from fn.llm import FixtureMissing
from fn.steps import StepContext, fan_out

TASK = "scout"
BLOCKED = ("linkedin.com", "facebook.com", "x.com", "twitter.com", "instagram.com")
ANGLES = {
    "press": 'The press. Flemish and Belgian news sites and the question\'s own trade press, for articles and '
             'interviews about people from Belgium who hold this job in the United States ("Vlaming in New York", '
             '"Belgische ... in Amerika", "Belgian-born ...").',
    "lists": "Lists of people with the tie. Belgian-American chambers of commerce and their boards, Belgian clubs and "
             "societies in the US, alumni chapters of Flemish universities and business schools in the US, honorary "
             "consuls, the US offices of Belgian companies, and fellowship alumni pages. From those lists keep the "
             "people who hold the job the question asks for.",
    "born": "Biography phrases. Search for bios and profiles that say a person in this job was born, raised or "
            'educated in Belgium: "born in Belgium", "a native of Antwerp", "grew up in Ghent", "studied at KU '
            'Leuven", "geboren in", combined with the job and the place.',
    "place": "The job in the place, whatever the tie. Firms, institutions, associations, boards, speaker line-ups and "
             "team pages in the asked place for the asked job. Report the people who best fit the job and the "
             "subject. Look for a tie to Belgium on their bio page, and report them also when it shows none.",
    "place_tied": "The job in the place. Firms, institutions, associations, boards, speaker line-ups and team pages "
                  "in the asked place for the asked job. Check each person's bio page for a tie to Belgium and "
                  "report only the people whose pages show one.",
    "speakers": "Speakers. Line-ups and panels of recent conferences, webinars and events on the question's subject "
                "in the asked place or region. Report the speakers who hold the asked job today.",
    "boards": "Associations. Trade associations, industry groups and their boards and committees for the asked job "
              "in the asked place or region. Report the members who fit the question's subject.",
}


def angles(chips: Chips) -> list[str]:
    """The angle keys for the question: four for a must tie, six for a wished tie, four without a tie chip."""
    if parse.tie_must(chips):
        return ["press", "lists", "born", "place_tied"]
    if chips.tie is not None:
        return ["press", "lists", "born", "place", "speakers", "boards"]
    return ["place", "speakers", "boards", "lists"]


def page_key(url: str) -> str:
    """The address without its fragment and one trailing slash, so two spellings of a page compare equal."""
    return urldefrag(url)[0].removesuffix("/")


def fetchable(url: str) -> bool:
    """Whether FN may fetch the address: http or https, and a host that is not blocked or a subdomain of a blocked one."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme in ("http", "https") and not any(host == b or host.endswith(f".{b}") for b in BLOCKED)


def row(stage: str, kept: bool, reason: str, name: str = "", key: str = "-") -> Considered:
    return Considered(person_key=key, name=name, stage=stage, kept=kept, reason=reason)


def merge(answers: list[ScoutLeads]) -> tuple[list[ScoutLead], list[Considered]]:
    """The leads of all answers by cleaned name, in order of first report, with the rows for the leads left out."""
    merged: dict[str, ScoutLead] = {}
    considered = []
    for answer in answers:
        for lead in answer.people:
            name = clean_name(lead.name)
            if not (key := name_key(name)):
                considered.append(row("mention", False, "a lead without a name"))
                continue
            known = merged.get(key) or lead.model_copy(update={"name": name, "pages": []})
            pages = list(known.pages)
            seen = {page_key(p) for p in pages}
            for page in lead.pages:
                if fetchable(page) and page_key(page) not in seen:
                    seen.add(page_key(page))
                    pages.append(page)
            merged[key] = known.model_copy(update={"pages": pages})
    leads = []
    for key, lead in merged.items():
        if lead.pages:
            leads.append(lead)
        else:
            considered.append(row("mention", False, f"{lead.name}: no page FN may read", lead.name, key))
    return leads, considered


def find(ctx: StepContext, question: str, chips: Chips) -> tuple[list[ScoutLead], list[Considered]]:
    """The researcher's people for the question, one call per angle at once, merged by cleaned name.

    A failed angle gives a row. When every angle failed, the first error is raised, except when every error is a
    missing recording: then there are no leads and a note, so a replay of an older search ends ok.
    """
    keys = angles(chips)
    answers = fan_out(lambda k: ctx.llm.structured(TASK, {"question": question, "angle": ANGLES[k]}, ScoutLeads).value,
                      keys, min(len(keys), ctx.settings.llm_workers))
    considered, good = [], []
    for key, answer in zip(keys, answers):
        if isinstance(answer, Exception):
            considered.append(row("query", False, f"angle {key} failed: {type(answer).__name__}: {answer}"))
            continue
        good.append(answer)
        considered.append(row("query", True, f"angle {key}: {len(answer.people)} people; "
                                             f"searches: {' | '.join(answer.searches)}"))
    if not good:
        errors = [a for a in answers if isinstance(a, Exception)]
        if not all(isinstance(e, FixtureMissing) for e in errors):
            raise errors[0]
        return [], [*considered, row("query", False, "no recorded web research for this question")]
    leads, dropped = merge(good)
    return leads, considered + dropped
