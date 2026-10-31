"""Seed lane: topic and institution chips as a quoted FTS5 query over the seed claims."""
from collections.abc import Callable

from fn import ties
from fn.contracts import Chips, Considered, LaneHit, LaneIn, LaneName, LaneOut
from fn.steps import StepContext

name: LaneName = "seeds"
HIT_LIMIT = 100
NO_QUERY = "no topic or institution chip"


def phrase(text: str) -> str | None:
    """text as one FTS5 string with inner quotes doubled; None when it holds no letter or digit."""
    return f'"{text.replace('"', '""')}"' if any(c.isalnum() for c in text) else None


def fts_query(chips: Chips, aliases: Callable[[str], list[str]] = lambda _: []) -> str:
    """Every token of every topic and institution chip ORed, plus each institution's aliases as whole phrases.

    Tokens are quoted, so FTS5 operators and punctuation in a chip are plain text. Empty when no chip has a token.
    """
    terms = [phrase(t) for chip in [*chips.topics, *chips.institutions] for t in chip.text.split()]
    terms += [phrase(a) for chip in chips.institutions for a in aliases(chip.text)]
    return " OR ".join(dict.fromkeys(t for t in terms if t))


def run(ctx: StepContext, inp: LaneIn) -> LaneOut:
    query = fts_query(inp.chips, ties.aliases)
    if not query:
        return LaneOut(lane=name, query="", total_seen=0,
                       considered=[Considered(person_key="-", name="", stage="query", kept=False, reason=NO_QUERY)])
    hits, considered = [], []
    # OpenAlex records are ranked by their own lane; matching them here would make seed ranks depend on past searches.
    for rank, (person, claim, score) in enumerate(ctx.store.match_claims(query, exclude="record"), 1):
        kept = rank <= HIT_LIMIT
        if kept:
            hits.append(LaneHit(person_id=person.id, name_key=person.name_key, lane=name, rank=rank, score=-score,
                                matched_on=claim.value, claim_ids=[claim.id]))
        reason = f"fts rank {rank}, matched {claim.value!r}" if kept else f"fts rank {rank}, below the top {HIT_LIMIT}"
        considered.append(Considered(person_key=person.id, name=person.display_name, stage="fts", kept=kept,
                                     reason=reason))
    ctx.log.info("seed lane: %d people match %s", len(considered), query)
    return LaneOut(lane=name, query=query, total_seen=len(considered), hits=hits, considered=considered)
