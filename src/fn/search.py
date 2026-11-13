"""The Quick workflow: which steps run in which order."""
import argparse
import logging
import sys
from collections.abc import Callable

from fn import fitcheck, parse, rank, resolve
from fn.contracts import (
    Chips,
    Considered,
    FitIn,
    FitOut,
    LaneIn,
    LaneOut,
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
from fn.lanes import LANES
from fn.llm import StructuredLLM, from_settings
from fn.steps import StepContext, run_step, skip_step


def save(ctx: StepContext, inp: SaveIn) -> SaveOut:
    return SaveOut(count=ctx.store.save_candidates(ctx.search_id, inp.candidates, inp.flags))


def publish(outs: list[LaneOut]) -> Callable[[StepContext, PublishIn], PublishOut]:
    """The publish step over the lane outputs so far: it resolves, ranks and saves them as the final steps do.

    A lane that added no hits leaves the saved candidates as they are, so the step returns their count.
    """
    def step(ctx: StepContext, inp: PublishIn) -> PublishOut:
        if not outs[-1].hits:
            return PublishOut(count=len(ctx.store.list_candidates(ctx.search_id)))
        resolved = resolve.run(ctx, ResolveIn(outs=outs))
        ranked = rank.run(ctx, RankIn(entries=resolved.entries, chips=inp.chips))
        return save(ctx, SaveIn(candidates=ranked.candidates, flags=resolved.flags))
    return step


def rank_and_save(ctx: StepContext, resolved: ResolveOut, chips: Chips, fit: FitOut) -> None:
    ranked = run_step(ctx, "rank", rank.run,
                      RankIn(entries=resolved.entries, chips=chips, verdicts=fit.verdicts, unsure=fit.unsure))
    run_step(ctx, "save", save, SaveIn(candidates=ranked.candidates, flags=resolved.flags))


def finish(ctx: StepContext, outs: list[LaneOut], chips: Chips) -> None:
    """Run the steps after the lanes in order: resolve the lane outputs, rank the entries, save the candidates, ask
    the model which stored people fit the question, and rank and save again when it answered.

    A fit step that raises leaves the first ranking saved.
    """
    resolved = run_step(ctx, "resolve", resolve.run, ResolveIn(outs=outs))
    rank_and_save(ctx, resolved, chips, FitOut())
    try:
        fit = run_step(ctx, "fit", fitcheck.run, FitIn(question=ctx.store.get_search(ctx.search_id).question, chips=chips))
    except Exception:  # noqa: BLE001 any error is kept on the step row and the first ranking stands
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
    resolved = run_step(ctx, "resolve", resolve.run, ResolveIn(outs=outs))
    rank_and_save(ctx, resolved, search.chips, stored_fit(ctx))


def run(ctx: StepContext, search: Search) -> None:
    """Run the Quick steps in order: parse, each lane with a publish after all but the last, resolve, rank and save.

    A lane that raises keeps its error row and counts as an empty output; raises RuntimeError when every lane did.
    """
    inp = ParseIn(question=search.question)
    if search.chips is not None:
        chips = skip_step(ctx, "parse", inp, ParseOut(chips=search.chips)).chips
    else:
        chips = run_step(ctx, "parse", parse.run, inp).chips
        ctx.store.set_search_chips(search.id, chips, "parsed")
    lane_in = LaneIn(search_id=search.id, chips=chips, depth=search.depth, question=search.question)
    outs, failed = [], 0
    for i, lane in enumerate(LANES):
        try:
            if lane.name == "openalex" and not parse.wants_research(chips):
                outs.append(skip_step(ctx, "lane:openalex", lane_in, LaneOut(
                    lane="openalex", query="", total_seen=0,
                    considered=[Considered(person_key="-", name="", stage="query", kept=False,
                                           reason="no research asked")])))
            else:
                given = lane_in
                if lane.name == "web_topic":
                    given = lane_in.model_copy(update={"first_heading": first_heading(ctx)})
                outs.append(run_step(ctx, f"lane:{lane.name}", lane.run, given))
        except Exception:  # noqa: BLE001 any lane error is kept on its step row and the search goes on
            failed += 1
            outs.append(LaneOut(lane=lane.name, query="", total_seen=0))
        if i < len(LANES) - 1:
            run_step(ctx, "publish", publish(list(outs)), PublishIn(lanes=[o.lane for o in outs], chips=chips))
    if failed == len(LANES):
        raise RuntimeError("every lane failed")
    finish(ctx, outs, chips)


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
