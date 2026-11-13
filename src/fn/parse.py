"""Question to chips, and the check that every chip span points at its own text."""
import logging

from fn import orgs
from fn.contracts import Chip, Chips, ParseIn, ParseOut, Place, Span, name_key
from fn.steps import StepContext

log = logging.getLogger("fn.parse")

FUNCTION_WORDS = {name_key(w) for w in """
the a an and or but nor of in on at to for from by with without about as into over under between through during
before after up down out off than then so if while who whom whose which what when where why how that this these those
it its they them their he she his her we our you your i me my is are was were be been being am do does did have has
had having can could will would shall should may might must not no there here also very
de het een en of maar van in op aan te voor met zonder over uit bij naar tot door om als dat dit die deze wie wat
welke waar wanneer waarom hoe er is zijn was waren wordt worden werd hebben heeft had hadden kan kunnen zal zullen
moet moeten mag ik je jij u hij zij ze wij jullie hun hen hem haar ons onze mijn uw niet geen ook nog dan meer zeer
tussen onder na per
le la les un une des du et ou mais donc ni dans en sur sous avec sans pour par chez vers entre au aux ce cet cette
ces qui que quoi dont ou quel quelle quels quelles comment pourquoi quand est sont etait etaient etre ete suis es
sommes etes ont avait avoir peut peuvent pouvoir fait faire je tu il elle on nous vous ils elles te se lui leur
leurs son sa ses mon ma mes notre nos votre vos ne pas plus aussi tres
""".split()}
# A question is about people with a Belgian tie, so these words match almost every record.
GENERIC_WORDS = {name_key(w) for w in """
research researcher science scientist university expert experts people person tech technology us usa belgian belgium
flemish flanders onderzoek onderzoeker onderzoekers wetenschap wetenschapper universiteit experten mensen persoon
technologie belgisch belgische belgie vlaams vlaamse vlaanderen recherche chercheur chercheurs scientifique
universite personnes personne belge belges belgique flamand flamande flamands flandre
""".split()}
MAX_RELATED = 6
# Words that name a kind of person without saying which, so they are no help as a related word.
RELATED_SKIP = GENERIC_WORDS | {name_key(w) for w in """
specialist specialists professional professionals individual individuals staff member members specialiste specialistes
professionnel professionnels deskundige deskundigen vakman
""".split()}


class SpanError(ValueError):
    """The model's answer breaks a rule of the parse contract."""


def content_words(text: str) -> list[str]:
    """The words of text that carry meaning, folded like name_key, in order, once each.

    Function words (English, Dutch, French), generic words and single characters are left out.
    """
    skip = FUNCTION_WORDS | GENERIC_WORDS
    return [w for w in dict.fromkeys(name_key(text).split()) if w not in skip and len(w) > 1]


def chip_words(text: str) -> list[str]:
    """The content words of a topic chip as the matcher looks for them: a final s dropped from a word of four letters or more."""
    return [w[:-1] if w.endswith("s") and len(w) > 3 else w for w in content_words(text)]


def words_in(words: list[str], text: str) -> list[str]:
    """The words that stand at the start of a word of text, folded like name_key, in the order of words.

    A word of three letters or fewer must be the whole word, so "ai" does not find "aircraft".
    """
    tokens = name_key(text).split()
    return [w for w in words if any(t == w if len(w) <= 3 else t.startswith(w) for t in tokens)]


def topic_match(chips: list[str], texts: list[str]) -> bool:
    """Whether every chip word of at least one chip with content words stands in one of the texts."""
    wanted = [found for found in map(chip_words, chips) if found]
    return any(len(words_in(found, text)) == len(found) for found in wanted for text in texts)


def clean_related(chip: Chip) -> list[str]:
    """The related words of a chip, at most MAX_RELATED, each on one line.

    An entry stays when it has a content word that is not in RELATED_SKIP, differs from the chip's text and from
    every kept entry, and has a content word the chip's own text lacks.
    """
    own, seen, kept = set(content_words(chip.text)), {name_key(chip.text)}, []
    for entry in chip.related:
        entry = " ".join(entry.split())
        key = name_key(entry)
        mine = set(content_words(entry))
        if not (mine - RELATED_SKIP) or key in seen or mine <= own:
            continue
        seen.add(key)
        kept.append(entry)
    return kept[:MAX_RELATED]


def tie_must(chips: Chips) -> bool:
    """Whether the question requires a tie: false for chips stored before version 2, else whether the tie chip is a must."""
    return chips.version >= 2 and chips.tie is not None and chips.tie.need == "must"


def asks_researchers(chips: Chips) -> bool:
    """Whether the question asks for academic researchers: always for version 1 chips, else when a role chip says so."""
    return chips.version < 2 or any(r.research for r in chips.roles)


def wants_research(chips: Chips) -> bool:
    """Whether the question asks for research expertise: researchers asked for, or no role named."""
    return asks_researchers(chips) or not chips.roles


def _all_chips(chips: Chips) -> list[Chip | Place]:
    return [*chips.topics, *chips.institutions, *chips.roles, *([chips.tie] if chips.tie else []),
            *([chips.place] if chips.place else [])]


def locate(question: str, text: str, near: int | None) -> Span | None:
    """The span of text in question whose start is nearest to near (the first one when near is None or on a tie).

    Compared exactly first, then casefolded when that finds nothing. None when text stands nowhere or is empty.
    """
    if not text:
        return None
    folded = question.casefold(), text.casefold()
    for haystack, needle in ((question, text), folded if len(folded[0]) == len(question) else ("", text)):
        starts, at = [], haystack.find(needle)
        while at != -1:
            starts.append(at)
            at = haystack.find(needle, at + 1)
        if starts:
            start = min(starts, key=lambda s: abs(s - near)) if near is not None else starts[0]
            return Span(start=start, end=start + len(text))
    return None


def _checked[C: (Chip, Place)](question: str, chip: C) -> C | None:
    """The chip with a span on its text in question, or None when the text stands nowhere in it.

    A chip whose span already holds its text is returned as it is. An edited chip is never dropped and keeps its text.
    """
    span = chip.span
    if span is None and chip.origin == "edited":
        return chip
    if span is not None and 0 <= span.start < span.end <= len(question) and question[span.start:span.end] == chip.text:
        return chip
    fixed = locate(question, chip.text, span.start if span else None)
    if fixed is None:
        if chip.origin == "edited":
            return chip
        log.warning("chip %r is not in the question; dropped", chip.text)
        return None
    text = question[fixed.start:fixed.end]
    if span is None:
        log.info("span of chip %r set to [%d:%d]", chip.text, fixed.start, fixed.end)
    else:
        log.info("span of chip %r moved from [%d:%d] to [%d:%d]", chip.text, span.start, span.end, fixed.start, fixed.end)
    return chip.model_copy(update={"span": fixed} if chip.origin == "edited" else {"span": fixed, "text": text})


def check_spans(question: str, chips: Chips) -> Chips:
    """Return chips whose spans point at their own text in the question.

    A wrong or missing span is replaced by the occurrence of the text nearest to the claimed start, and a text that
    differs only in case becomes the question's own slice. A parsed chip whose text stands nowhere is dropped.
    """
    def keep(found: list[Chip]) -> list[Chip]:
        return [c for c in (_checked(question, c) for c in found) if c is not None]

    result = chips.model_copy(update={
        "topics": keep(chips.topics),
        "institutions": keep(chips.institutions),
        "roles": keep(chips.roles),
        "tie": _checked(question, chips.tie) if chips.tie else None,
        "place": _checked(question, chips.place) if chips.place else None,
    })
    return chips if result == chips else result


def run(ctx: StepContext, inp: ParseIn) -> ParseOut:
    """Ask the LLM for chips and return them once their spans check out.

    Any ref from the model is dropped; an institution chip gets its ror: ref from data/org_aliases.csv only.
    Raises SpanError for a model answer that claims an edited chip.
    """
    if ctx.llm is None:
        raise RuntimeError("the parse step needs an LLM")
    chips = ctx.llm.structured("parse", {"question": inp.question}, Chips).value
    if any(chip.origin == "edited" for chip in _all_chips(chips)):
        raise SpanError("the model returned a chip with origin 'edited'")
    chips = chips.model_copy(update={
        "topics": [c.model_copy(update={"ref": None, "related": clean_related(c), "research": None}) for c in chips.topics],
        "institutions": [c.model_copy(update={"ref": orgs.ref(c.text), "related": [], "research": None})
                         for c in chips.institutions],
        "roles": [c.model_copy(update={"ref": None, "related": clean_related(c), "research": bool(c.research)})
                  for c in chips.roles],
        "tie": chips.tie.model_copy(update={"ref": None, "related": [], "research": None}) if chips.tie else None,
        "version": 2,
    })
    return ParseOut(chips=check_spans(inp.question, chips))
