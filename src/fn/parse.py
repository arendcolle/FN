"""Question to chips, and the check that every chip span points at its own text."""
import logging

from fn import ties
from fn.contracts import Chip, Chips, ParseIn, ParseOut, Place, Span
from fn.steps import StepContext

log = logging.getLogger("fn.parse")

# The model's character offsets are sometimes off by one; a larger shift means a made-up position.
SPAN_SLACK = 2


class SpanError(ValueError):
    """A chip's span is out of range or does not hold the chip's text."""


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

    Any ref from the model is dropped; an institution chip gets its ref from ties.csv only.
    Raises SpanError for a bad or missing span, and for a model answer that claims an edited chip.
    """
    if ctx.llm is None:
        raise RuntimeError("the parse step needs an LLM")
    chips = ctx.llm.structured("parse", {"question": inp.question}, Chips).value
    if any(chip.origin == "edited" for chip in _all_chips(chips)):
        raise SpanError("the model returned a chip with origin 'edited'")
    chips = chips.model_copy(update={
        "topics": [c.model_copy(update={"ref": None}) for c in chips.topics],
        "institutions": [c.model_copy(update={"ref": ties.ref(c.text)}) for c in chips.institutions],
    })
    return ParseOut(chips=check_spans(inp.question, chips))
