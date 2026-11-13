"""Ask the model which stored people fit the question, from what their claims say about their work."""
from fn import rank
from fn.contracts import Candidate, Claim, FitAnswer, FitIn, FitOut, FitVerdict, Org
from fn.llm import FixtureMissing
from fn.steps import StepContext, fan_out

TASK = "fit"
MAX_PEOPLE = 60
BATCH = 20
LINE_WORDS = 40
EMPLOYER = ("works_at", "affiliated_with")


def newest(claim: Claim) -> int:
    """The latest year a claim covers, 0 when it has none."""
    return max((int(u) for u in rank.units(claim) if u != rank.UNDATED), default=0)


def line_of(claims: list[Claim], facts: dict[str, Org]) -> str:
    """What the model reads about one person, at most LINE_WORDS words, joined by '; ': the role values, the
    employers, then the topic claims (papers included), newest first. No name, place or tie claim."""
    roles = [c.value for c in claims if c.kind == "role" and c.relation is None]
    employers = [facts[c.org_id].name if c.org_id in facts else c.value for c in claims if c.relation in EMPLOYER]
    topics = [c.value for c in sorted((c for c in claims if c.kind == "topic"), key=newest, reverse=True)]
    parts = list(dict.fromkeys(p.strip() for p in (*roles, *employers, *topics) if p.strip()))
    return " ".join("; ".join(parts).split()[:LINE_WORDS])


def candidates(ranked: list[Candidate]) -> list[Candidate]:
    """The kept people of the new section in tiers 1 to 4 whom the web researcher did not find, in rank order, at
    most MAX_PEOPLE: the researcher chose its people for the question already."""
    found = [c for c in ranked if c.section == "new" and c.cut_reason is None and c.tier in (1, 2, 3, 4)
             and "scout" not in c.lane_ranks]
    return sorted(found, key=lambda c: c.rank)[:MAX_PEOPLE]


def run(ctx: StepContext, inp: FitIn) -> FitOut:
    """Ask the model about the candidates in batches of BATCH and return a verdict per person it answered for;
    unsure names the people it sent and got no verdict for.

    No call for chips stored before version 2 or without a candidate. A failed batch adds nothing and names its error
    in the note; when every batch failed, the first error is raised, except a run of missing recordings, which gives
    a note and ends ok.
    """
    if inp.chips.version < 2:
        return FitOut(note="chips stored before this round, so no fit check")
    people = candidates(ctx.store.list_candidates(ctx.search_id, kept_only=True))
    if not people:
        return FitOut(note="nobody to check")
    records = list(dict.fromkeys(p for c in people for p in c.card_person_ids or c.hit_person_ids or c.person_ids[:1]))
    claims = ctx.store.claims_of(records)
    facts = ctx.store.get_orgs(list(dict.fromkeys(c.org_id for c in claims if c.org_id)))
    by_person: dict[str, list[Claim]] = {}
    for c in claims:
        by_person.setdefault(c.person_id, []).append(c)
    lines = [line_of([c for p in (x.card_person_ids or x.hit_person_ids or x.person_ids[:1]) for c in by_person.get(p, [])],
                     facts) for x in people]
    batches = [(people[i:i + BATCH], lines[i:i + BATCH]) for i in range(0, len(people), BATCH)]

    def ask(batch: tuple[list[Candidate], list[str]]) -> FitAnswer:
        text = "\n".join(f"{n}. {line}" for n, line in enumerate(batch[1], 1))
        return ctx.llm.structured(TASK, {"question": inp.question, "people": text}, FitAnswer).value

    answers = fan_out(ask, batches, min(len(batches), ctx.settings.llm_workers))
    verdicts: dict[str, FitVerdict] = {}
    errors = [a for a in answers if isinstance(a, Exception)]
    if len(errors) == len(answers):
        if not all(isinstance(e, FixtureMissing) for e in errors):
            raise errors[0]
        return FitOut(note="no recorded fit check for this question")
    for (batch, _), answer in zip(batches, answers):
        if isinstance(answer, Exception):
            continue
        for row in answer.people:
            if 1 <= row.n <= len(batch):
                verdicts.setdefault(batch[row.n - 1].person_id, row.fit)
    notes = [f"batch {n} failed: {type(a).__name__}: {a}" for n, a in enumerate(answers, 1) if isinstance(a, Exception)]
    unsure = [c.person_id for c in people if c.person_id not in verdicts]
    return FitOut(verdicts=verdicts, unsure=unsure, note="; ".join(notes))
