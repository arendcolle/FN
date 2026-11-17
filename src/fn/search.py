"""The Quick workflow: which steps run in which order."""
import argparse
import logging
import sys
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextvars import copy_context

from fn import deepen, fitcheck, geo, orgs, parse, rank, resolve
from fn.contracts import (
    Chips,
    CitiesIn,
    CitiesOut,
    Considered,
    DeepenIn,
    DeepenOut,
    FitIn,
    FitOut,
    LaneIn,
    LaneOut,
    OrgMatchIn,
    ParseIn,
    ParseOut,
    PublishIn,
    PublishOut,
    RankIn,
    ResolveIn,
    ResolveOut,
    SaveIn,
    SaveOut,
    Search,
)
from fn.lanes import LANES, Lane
from fn.llm import StructuredLLM, from_settings
from fn.net import HttpError
from fn.steps import StepContext, run_step, skip_step

# The lane that runs alone and is published before any other lane starts, since it reads what they write.
FIRST = "seeds"
# The lane that starts only once every lane before it in LANES has ended and been published.
WAITS = "web_topic"
# The most employer names the link step asks ROR about during one search.
LINK_MOST = 40


def save(ctx: StepContext, inp: SaveIn) -> SaveOut:
    return SaveOut(count=ctx.store.save_candidates(ctx.search_id, inp.candidates, inp.flags))


def cities(ctx: StepContext, _: CitiesIn) -> CitiesOut:
    """Build the city index once before the lanes start; a failed fetch logs a warning and counts 0 names."""
    try:
        return CitiesOut(names=len(geo.cities(ctx.http)))
    except HttpError as exc:
        ctx.log.warning("the city index could not be fetched: %s", exc)
        return CitiesOut(names=0)


def lane_index(name: str) -> int:
    """The place of lane `name` in LANES, after every lane when it is missing from LANES."""
    names = [lane.name for lane in LANES]
    return names.index(name) if name in names else len(names)


def in_lane_order(outs: list[LaneOut]) -> list[LaneOut]:
    """The lane outputs in the order of LANES, a lane missing from LANES last; outputs of one lane keep their order."""
    return sorted(outs, key=lambda out: lane_index(out.lane))


def publish(outs: list[LaneOut], done: LaneOut) -> Callable[[StepContext, PublishIn], PublishOut]:
    """The publish step over the lane outputs so far, after lane `done` ended: it resolves, ranks and saves them as the
    final steps do.

    A lane that added no hits leaves the saved candidates as they are, so the step returns their count.
    """
    def step(ctx: StepContext, inp: PublishIn) -> PublishOut:
        if not done.hits:
            return PublishOut(count=len(ctx.store.list_candidates(ctx.search_id)))
        resolved = resolve.run(ctx, ResolveIn(outs=outs))
        ranked = rank.run(ctx, RankIn(entries=resolved.entries, chips=inp.chips))
        return save(ctx, SaveIn(candidates=ranked.candidates, flags=resolved.flags))
    return step


def rank_and_save(ctx: StepContext, resolved: ResolveOut, chips: Chips, fit: FitOut) -> None:
    ranked = run_step(ctx, "rank", rank.run,
                      RankIn(entries=resolved.entries, chips=chips, verdicts=fit.verdicts, unsure=fit.unsure))
    run_step(ctx, "save", save, SaveIn(candidates=ranked.candidates, flags=resolved.flags))


def link(ctx: StepContext, people: list[str]) -> None:
    """Run the link step for the people's employer names; its failure is kept on its row and the search goes on."""
    try:
        run_step(ctx, "link", orgs.match, OrgMatchIn(person_ids=people, most=LINK_MOST, pace_s=orgs.SEARCH_PACE_S))
    except Exception:  # noqa: BLE001 the error is kept on the step row and the people keep an unknown place
        pass


def look_up(ctx: StepContext, inp: DeepenIn) -> DeepenOut:
    """Run the deepen step; an exception stays on its row and gives an empty output."""
    try:
        return run_step(ctx, deepen.STEP, deepen.run, inp)
    except Exception:  # noqa: BLE001 any error is kept on the step row and the ranking before it stands
        return DeepenOut()


def first_pass(ctx: StepContext, chips: Chips) -> DeepenOut:
    """Run the first lookup pass on a lane thread and close the thread's connection."""
    try:
        return look_up(ctx, DeepenIn(chips=chips))
    finally:
        ctx.store.close()


def finish(ctx: StepContext, outs: list[LaneOut], chips: Chips, first: DeepenOut) -> None:
    """Run the steps after the lanes in order: link the employers of the hit people, resolve the lane outputs, rank the
    entries, save the candidates, run the second lookup pass for people the first pass left out, ask the model
    which stored people fit the question, and rank and save again after each of the last two when it changed something.

    The first pass ran after the seeds publish, the second runs after the first save. The link step runs with version 2
    chips and an HTTP client, and again after a second pass that added claims. A lookup or fit step that raises leaves
    the ranking before it saved.
    """
    linking = ctx.http is not None and chips.version >= 2
    by_rank = sorted((h for out in outs for h in out.hits), key=lambda h: h.rank)
    hit = list(dict.fromkeys(h.person_id for h in by_rank))
    if linking:
        link(ctx, hit)
    resolved = run_step(ctx, "resolve", resolve.run, ResolveIn(outs=outs))
    rank_and_save(ctx, resolved, chips, FitOut())
    deepened = look_up(ctx, DeepenIn(chips=chips, skip=first.picked, used=first.gaps))
    if deepened.claim_ids:
        if linking:
            link(ctx, hit)
        rank_and_save(ctx, resolved, chips, FitOut())
    try:
        fit = run_step(ctx, "fit", fitcheck.run, FitIn(question=ctx.store.get_search(ctx.search_id).question, chips=chips))
    except Exception:  # noqa: BLE001 any error is kept on the step row and the ranking before it stands
        return
    if fit.verdicts:
        rank_and_save(ctx, resolved, chips, fit)


def stored_fit(ctx: StepContext) -> FitOut:
    """The output of the search's last fit step that ended ok, else an empty one."""
    for step in reversed(ctx.store.list_steps(ctx.search_id)):
        if step.step == "fit" and step.status == "ok":
            output = ctx.store.get_payload(step.id)[1]
            return FitOut.model_validate_json(output) if output else FitOut()
    return FitOut()


def first_heading(ctx: StepContext) -> int:
    """How many kept people of the new section the saved candidates put in tier 1 or 2."""
    kept = ctx.store.list_candidates(ctx.search_id, kept_only=True)
    return sum(c.section == "new" and c.tier in (1, 2) for c in kept)


def refinish(ctx: StepContext, search: Search) -> None:
    """Resolve, rank and save the stored outputs of the search's lane steps with its stored chips and the verdicts of
    its last fit step, and make no model call.

    A lane step that did not end ok counts as an empty output. Raises ValueError with the search id when
    no lane step has a stored output.
    """
    outs, stored = [], 0
    for step in (s for s in ctx.store.list_steps(search.id) if s.step.startswith("lane:")):
        output = ctx.store.get_payload(step.id)[1] if step.status == "ok" else None
        stored += bool(output)
        outs.append(LaneOut.model_validate_json(output) if output else LaneOut(lane=step.step[5:], query="", total_seen=0))
    if not stored:
        raise ValueError(f"search {search.id} has no stored lane outputs")
    resolved = run_step(ctx, "resolve", resolve.run, ResolveIn(outs=in_lane_order(outs)))
    rank_and_save(ctx, resolved, search.chips, stored_fit(ctx))


def run_lane(ctx: StepContext, lane: Lane, given: LaneIn) -> tuple[LaneOut, bool]:
    """Run one lane as step lane:<name> on a lane thread and close the thread's connection: its output and whether it
    raised.

    A lane that raises keeps its error row and gives an empty output.
    """
    try:
        if lane.name == "openalex" and not parse.wants_research(given.chips):
            return skip_step(ctx, "lane:openalex", given, LaneOut(
                lane="openalex", query="", total_seen=0,
                considered=[Considered(person_key="-", name="", stage="query", kept=False,
                                       reason="no research asked")])), False
        return run_step(ctx, f"lane:{lane.name}", lane.run, given), False
    except Exception:  # noqa: BLE001 any lane error is kept on its step row and the search goes on
        return LaneOut(lane=lane.name, query="", total_seen=0), True
    finally:
        ctx.store.close()


def run(ctx: StepContext, search: Search) -> None:
    """Run the Quick steps: parse, cities, the seeds lane alone, then the other lanes side by side, with a publish as
    each lane ends but the last, then the steps after the lanes.

    The first lookup pass starts after the seeds publish, beside the other lanes, and the steps after the lanes wait
    for it. The web_topic lane starts once every lane before it has ended and been published. A lane that raises keeps
    its error row and counts as an empty output; raises RuntimeError when every lane did.
    """
    inp = ParseIn(question=search.question)
    if search.chips is not None:
        chips = skip_step(ctx, "parse", inp, ParseOut(chips=search.chips)).chips
    else:
        chips = run_step(ctx, "parse", parse.run, inp).chips
        ctx.store.set_search_chips(search.id, chips, "parsed")
    if ctx.http is not None:
        try:
            run_step(ctx, "cities", cities, CitiesIn())
        except Exception:  # noqa: BLE001 the error is kept on the step row and a lane builds the index when it needs it
            pass
    lane_in = LaneIn(search_id=search.id, chips=chips, depth=search.depth, question=search.question)
    outs: list[LaneOut | None] = [None] * len(LANES)
    failed, started = 0, None
    with ThreadPoolExecutor(max_workers=len(LANES) + 1, thread_name_prefix="fn-lane") as pool:
        def submit(i: int, given: LaneIn) -> Future[tuple[LaneOut, bool]]:
            return pool.submit(copy_context().run, run_lane, ctx, LANES[i], given)

        def ready(i: int) -> bool:
            if LANES[i].name == FIRST:
                return True
            if any(outs[j] is None for j, lane in enumerate(LANES) if lane.name == FIRST):
                return False
            return LANES[i].name != WAITS or None not in outs[:i]

        waiting, pending = list(range(len(LANES))), {}
        while waiting or pending:
            for i in [i for i in waiting if ready(i)]:
                waiting.remove(i)
                given = lane_in
                if LANES[i].name == WAITS:
                    given = lane_in.model_copy(update={"first_heading": first_heading(ctx)})
                pending[submit(i, given)] = i
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in sorted(done, key=pending.__getitem__):
                i = pending.pop(future)
                outs[i], error = future.result()
                failed += error
                filled = [o for o in outs if o is not None]
                if len(filled) < len(LANES):
                    given = PublishIn(lanes=[o.lane for o in filled], chips=chips)
                    run_step(ctx, "publish", publish(filled, outs[i]), given)
                    if LANES[i].name == FIRST:
                        started = pool.submit(copy_context().run, first_pass, ctx, chips)
    if failed == len(LANES):
        raise RuntimeError("every lane failed")
    first = started.result() if started else DeepenOut()
    finish(ctx, in_lane_order(outs), chips, first)


def main(argv: list[str] | None = None, llm: StructuredLLM | None = None) -> int:
    """Run one search for the question in argv in the foreground and print its steps.

    Returns 0 when the search ends done, else 1.
    """
    from fn import config, net
    from fn.store import Store
    from fn.worker import Worker

    question = " ".join(sys.argv[1:] if argv is None else argv)
    settings = config.from_env()
    store = Store(settings.db_path)
    store.migrate()
    worker = Worker(store, settings, llm=llm or from_settings(settings), http=net.Client(settings))
    found = worker.execute(worker.create_search(question).id)
    print(f"search {found.id} {found.status}")
    for step in store.list_steps(found.id):
        print(f"  {step.seq} {step.step} {step.status} {step.error_type or ''}".rstrip())
    return 0 if found.status == "done" else 1


def rerank_main(argv: list[str] | None = None) -> int:
    """fn-rerank SEARCH_ID... | --all: run refinish on stored searches in the settings' database and print, per search,
    the people kept before and after.

    --all takes every finished search. Returns 0, or 1 when a search is unknown or has no stored lane outputs.
    """
    from fn import config, net
    from fn.store import Store
    from fn.worker import new_id, now

    parser = argparse.ArgumentParser(prog="fn-rerank")
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if bool(args.ids) == args.all:
        parser.error("give search ids or --all")
    settings = config.from_env()
    store = Store(settings.db_path)
    store.migrate()
    http = net.Client(settings)
    found = [s for s in store.list_searches(None) if s.status == "done"] if args.all else [store.get_search(i) for i in args.ids]
    failed = 0
    for wanted, stored in zip(args.ids or [s.id for s in found], found, strict=True):
        if stored is None:
            print(f"{wanted}: no such search")
            failed += 1
            continue
        before = store.count_candidates([stored.id]).get(stored.id, 0)
        ctx = StepContext(search_id=stored.id, store=store, llm=None, http=http, now=now, new_id=new_id,
                          log=logging.getLogger("fn.rerank"), settings=settings)
        try:
            refinish(ctx, stored)
        except ValueError as exc:
            print(f"{stored.id}: {exc}")
            failed += 1
            continue
        print(f"{stored.id}: kept {before} -> {store.count_candidates([stored.id]).get(stored.id, 0)}")
    store.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
