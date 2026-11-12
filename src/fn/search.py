"""The Quick workflow: which steps run in which order."""
import sys
from collections.abc import Callable

from fn import parse, rank, resolve
from fn.contracts import (
    Chips,
    LaneIn,
    LaneOut,
    ParseIn,
    ParseOut,
    PublishIn,
    PublishOut,
    RankIn,
    ResolveIn,
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
    """The publish step over the lane outputs so far: it resolves, ranks and saves them as the final steps do."""
    def step(ctx: StepContext, inp: PublishIn) -> PublishOut:
        resolved = resolve.run(ctx, ResolveIn(outs=outs))
        ranked = rank.run(ctx, RankIn(entries=resolved.entries, chips=inp.chips))
        return save(ctx, SaveIn(candidates=ranked.candidates, flags=resolved.flags))
    return step


def finish(ctx: StepContext, outs: list[LaneOut], chips: Chips) -> None:
    """Run the steps after the lanes in order: resolve the lane outputs, rank the entries and save the candidates."""
    resolved = run_step(ctx, "resolve", resolve.run, ResolveIn(outs=outs))
    ranked = run_step(ctx, "rank", rank.run, RankIn(entries=resolved.entries, chips=chips))
    run_step(ctx, "save", save, SaveIn(candidates=ranked.candidates, flags=resolved.flags))


def refinish(ctx: StepContext, search: Search) -> None:
    """Run finish over the stored outputs of the search's lane steps and its stored chips.

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
    finish(ctx, outs, search.chips)


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
    lane_in = LaneIn(search_id=search.id, chips=chips, depth=search.depth)
    outs, failed = [], 0
    for i, lane in enumerate(LANES):
        try:
            outs.append(run_step(ctx, f"lane:{lane.name}", lane.run, lane_in))
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


if __name__ == "__main__":
    sys.exit(main())
