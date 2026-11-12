"""Question to chips, and the check that every chip span points at its own text."""
import logging

from fn import orgs
from fn.contracts import Chip, Chips, ParseIn, ParseOut, Place, Span, name_key
from fn.steps import StepContext

log = logging.getLogger("fn.parse")

# The model's character offsets are sometimes off by one; a larger shift means a made-up position.
SPAN_SLACK = 2

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


class SpanError(ValueError):
    """A chip's span is out of range or does not hold the chip's text."""


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


def _all_chips(chips: Chips) -> list[Chip | Place]:
    return [*chips.topics, *chips.institutions, *([chips.place] if chips.place else [])]


def _nearby(question: str, text: str, start: int) -> Span | None:
    """The span of text in question that starts within SPAN_SLACK characters of start, if any."""
    for shift in sorted(range(-SPAN_SLACK, SPAN_SLACK + 1), key=abs):
        at = start + shift
        if at >= 0 and question[at:at + len(text)] == text:
            return Span(start=at, end=at + len(text))
    return None


def check_spans(question: str, chips: Chips) -> Chips:
    """Return chips whose spans match the question; raise SpanError otherwise.

    A span off by at most SPAN_SLACK characters is moved onto the chip's text and logged;
    chips come back unchanged when nothing moved. Only an edited chip may lack a span.
    """
    moved: dict[int, Span] = {}
    for chip in _all_chips(chips):
        span = chip.span
        if span is None:
            if chip.origin == "edited":
                continue
            raise SpanError(f"chip {chip.text!r} has no span")
        found = question[span.start:span.end] if 0 <= span.start < span.end <= len(question) else None
        if found == chip.text:
            continue
        fixed = _nearby(question, chip.text, span.start) if chip.text else None
        if fixed is None:
            raise SpanError(f"chip {chip.text!r} claims [{span.start}:{span.end}] of the question, which holds {found!r}")
        log.info("span of chip %r moved from [%d:%d] to [%d:%d]", chip.text, span.start, span.end, fixed.start, fixed.end)
        moved[id(chip)] = fixed
    if not moved:
        return chips

    def fix[C: (Chip, Place)](chip: C) -> C:
        return chip.model_copy(update={"span": moved[id(chip)]}) if id(chip) in moved else chip

    return chips.model_copy(update={
        "topics": [fix(c) for c in chips.topics],
        "institutions": [fix(c) for c in chips.institutions],
        "place": fix(chips.place) if chips.place else None,
    })


def run(ctx: StepContext, inp: ParseIn) -> ParseOut:
    """Ask the LLM for chips and return them once their spans check out.

    Any ref from the model is dropped; an institution chip gets its ror: ref from data/org_aliases.csv only.
    Raises SpanError for a bad or missing span, and for a model answer that claims an edited chip.
    """
    if ctx.llm is None:
        raise RuntimeError("the parse step needs an LLM")
    chips = ctx.llm.structured("parse", {"question": inp.question}, Chips).value
    if any(chip.origin == "edited" for chip in _all_chips(chips)):
        raise SpanError("the model returned a chip with origin 'edited'")
    chips = chips.model_copy(update={
        "topics": [c.model_copy(update={"ref": None}) for c in chips.topics],
        "institutions": [c.model_copy(update={"ref": orgs.ref(c.text)}) for c in chips.institutions],
    })
    return ParseOut(chips=check_spans(inp.question, chips))
