"""Web-topic lane: a web search for the topic, role and institution chips without a tie, when few people have one."""
from fn import parse, websearch
from fn.contracts import LaneIn, LaneName, LaneOut
from fn.lanes import web
from fn.steps import StepContext

name: LaneName = "web_topic"
GATE = 20


def run(ctx: StepContext, inp: LaneIn) -> LaneOut:
    """Search the web without the Belgian tie, or return a note and make no call.

    Notes: no topic, role or institution chip; chips stored before version 2; the tie is a must; GATE or more
    people under the first heading. Raises as web.collect does.
    """
    chips = inp.chips
    if not web.has_query(chips):
        reason = web.NO_QUERY
    elif chips.version == 1:
        reason = "chips stored before this round, so no search without a tie"
    elif parse.tie_must(chips):
        reason = "the tie is a must, so no search without it"
    elif (first := inp.first_heading or 0) >= GATE:
        reason = f"{first} people under the first heading, so no search without a tie"
    else:
        ctx.log.info("web_topic lane: %d people under the first heading, searched without a tie",
                     inp.first_heading or 0)
        return web.collect(ctx, web.objective(chips, tie=False), websearch.rule_queries(chips), name)
    return LaneOut(lane=name, query="", total_seen=0, considered=[web.note(reason)])
