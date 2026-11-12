"""Read models for the owner: where searches spend their time and what staff did with their results."""
from collections import defaultdict
from statistics import median

from fn.contracts import LaneName, SearchFeedback, SearchStat, StepStat
from fn.store import Store

QUESTION_CHARS = 80


def steps(store: Store, last: int = 20) -> list[StepStat]:
    """Per step name over the newest searches: runs, errors, median and slowest seconds, median cost and calls."""
    by_step = defaultdict(list)
    for row in store.step_stat_rows(last):
        by_step[row["step"]].append(row)
    stats = []
    for name, rows in sorted(by_step.items()):
        seconds = [r["seconds"] for r in rows if r["seconds"] is not None]
        stats.append(StepStat(
            step=name, runs=len(rows), errors=sum(r["status"] == "error" for r in rows),
            median_seconds=median(seconds) if seconds else None, slowest_seconds=max(seconds, default=None),
            median_cost_usd=median(r["cost_usd"] for r in rows), median_calls=median(r["calls"] for r in rows),
        ))
    return stats


def searches(store: Store, last: int = 20) -> list[SearchStat]:
    """Per search, newest first: status, total seconds, cost, people saved and seconds to the first person."""
    return [
        SearchStat(search_id=r["id"], question=r["question"][:QUESTION_CHARS], status=r["status"], seconds=r["seconds"],
                   cost_usd=r["cost_usd"], people=r["people"], first_person_seconds=r["first_seconds"])
        for r in store.search_stat_rows(last)
    ]


def feedback(store: Store, last: int = 50) -> list[SearchFeedback]:
    """Per search with a staff decision, newest first: people kept and cut, added and skipped, and where adds came from.

    Only decisions that no undo reversed count. An added person's lanes are the lanes in their candidate's lane ranks.
    """
    decisions = defaultdict(list)
    for event, undone in store.search_decisions(last):
        decisions[event.search_id].append((event, undone))
    found = sorted((store.get_search(i) for i in decisions), key=lambda s: s.created_at, reverse=True)
    result = []
    for search in found:
        search_id = search.id
        candidates = store.list_candidates(search_id)
        lanes: dict[LaneName, int] = defaultdict(int)
        adds = [e for e, undone in decisions[search_id] if e.kind == "add" and not undone]
        for event in adds:
            match = next((c for c in candidates if event.person_id in (c.person_id, *c.person_ids, *c.hit_person_ids)), None)
            for lane in match.lane_ranks if match else ():
                lanes[lane] += 1
        result.append(SearchFeedback(
            search_id=search_id, question=search.question[:QUESTION_CHARS],
            kept=sum(c.cut_reason is None for c in candidates), cut=sum(c.cut_reason is not None for c in candidates),
            added=len(adds), skipped=sum(e.kind == "skip" and not undone for e, undone in decisions[search_id]),
            added_ranks=[e.rank for e in adds if e.rank is not None], added_by_lane=dict(lanes),
        ))
    return result
