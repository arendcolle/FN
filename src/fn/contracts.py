"""Every value that crosses a module boundary in fn."""
import hashlib
import json
import re
import unicodedata
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal, Protocol

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationInfo,
    field_validator,
    model_validator,
)

CONTRACTS_VERSION = "2"
NORMALIZE_VERSION = 1

ListStatus = Literal["candidate", "in_list", "skipped"]
Section = Literal["network", "new"]
ClaimKind = Literal["topic", "affiliation", "role", "location", "availability", "email", "phone"]
Relation = Literal[
    "studied_at", "works_at", "worked_at", "affiliated_with", "hosted_by",
    "fellow_of", "member_of", "consul_for", "born_in", "lives_in",
]
DateMethod = Literal[
    "page_date", "sitemap", "wayback_first_seen", "document_heading",
    "record_field", "read_date", "sheet_date", "staff_edit", "stated_in_quote",
]
DatePrecision = Literal["year", "month", "day"]
SourceKind = Literal["page", "record", "seed_page", "import", "vendor_record", "vendor_page", "staff"]
StepStatus = Literal["running", "ok", "error", "skipped", "interrupted"]
SearchStatus = Literal["queued", "running", "done", "failed", "interrupted"]
SearchKind = Literal["search", "job"]
LaneName = Literal["seeds", "openalex", "web", "linkedin"]
ChipOrigin = Literal["parsed", "edited"]
Depth = Literal["quick"]
IdentifierScheme = Literal["seed", "openalex", "orcid", "profile_url", "mention", "email", "import"]
Ask = Literal["talk", "mentor", "host", "join", "other"]
PlaceKind = Literal["metro", "anywhere_us", "abroad"]
CallKind = Literal["http", "llm"]
LLMMode = Literal["live", "record", "replay", "prefer"]
CacheMode = Literal["refresh", "prefer", "only"]
GoldTie = Literal["flemish", "belgian", "none", "unverified"]
PickVerdict = Literal["found", "event page", "missed", "no lane in slice"]
GoldGroup = Literal["dev", "held-out", "other"]
EventKind = Literal["add", "skip", "merge", "not_same", "reject_claim", "edit_contact", "remove", "import", "export", "undo"]
CutReason = Literal["no_belgian_evidence"]
AddedVia = Literal["search", "import", "profile"]
# Ids the alias file holds and fn-orgs fetches; org rows from the OpenAlex lane may also use openalex: ids.
REGISTRY_ID = re.compile(r"ror:0[a-z0-9]{6}[0-9]{2}|wikidata:Q[0-9]+")
ORG_ID = re.compile(rf"{REGISTRY_ID.pattern}|openalex:I[0-9]+")


def normalize(text: str) -> str:
    """NFC, NBSP to space, straight quotes, single spaces, newlines kept; bump NORMALIZE_VERSION on any change."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace(" ", " ").replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"').replace("„", '"').replace("‚", "'")
    return "\n".join(line.strip() for line in re.sub(r"[^\S\n]+", " ", text).split("\n")).strip()


def name_key(name: str) -> str:
    """Fold a name for grouping: accents and case dropped, letters and digits only, single spaces."""
    bare = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", bare.casefold()))


def group_key(key: str) -> str:
    """A name_key without its middle initials, so 'nick m vandewiele' and 'nick vandewiele' share one card."""
    tokens = key.split()
    return " ".join([tokens[0], *(t for t in tokens[1:-1] if len(t) > 1), tokens[-1]]) if len(tokens) > 2 else key


TITLES = re.compile(r"^(?:(?:prof|dr|ir|mr|ms)(?:\.\s*|\s+))+", re.IGNORECASE)
# PhD in any case, but MBA and MD only in one case, so surnames such as Mba stay.
CREDENTIALS = re.compile(r"(?:[\s,]+(?:(?i:PhD|Ph\.D)|MBA|mba|MD|md)\.?)+$")


def clean_name(name: str) -> str:
    """The name on one line, without leading titles (Prof., Dr., Mr., Ms.) and trailing credentials (PhD, MBA, MD)."""
    return CREDENTIALS.sub("", TITLES.sub("", " ".join(normalize(name).split()))).strip(" ,")


class HttpClient(Protocol):
    def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response: ...

    def post(self, url: str, body: dict, params: dict[str, str] | None = None, *, timeout_s: float | None = None,
             cost: Callable[[bytes], float | None] | None = None, keep: Callable[[bytes], bool] | None = None,
             cache: CacheMode = "refresh") -> httpx.Response: ...


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Span(Model):
    start: int
    end: int


class Chip(Model):
    text: str
    span: Span | None = None
    origin: ChipOrigin
    ref: str | None = None


class Place(Model):
    text: str
    span: Span | None = None
    origin: ChipOrigin
    kind: PlaceKind | None = None


class Chips(Model):
    topics: list[Chip] = []
    institutions: list[Chip] = []
    place: Place | None = None
    ask: Ask | None = None


class Search(Model):
    id: str
    kind: SearchKind = "search"
    question: str
    depth: Depth = "quick"
    chips: Chips | None = None
    chips_origin: ChipOrigin | None = None
    status: SearchStatus
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None
    rerun_of: str | None = None
    code_sha: str | None
    dirty: bool
    llm_mode: LLMMode
    settings_json: str
    boot_id: str
    user_id: None = None


class Source(Model):
    id: str
    kind: SourceKind
    url: str
    title: str | None = None
    text: str
    raw_json: str | None = None
    content_hash: str
    normalize_version: int = NORMALIZE_VERSION
    source_date: str | None = None
    date_method: DateMethod | None = None
    fetched_at: datetime | None = None

    @field_validator("url")
    @classmethod
    def _http_only(cls, url: str, info: ValidationInfo) -> str:
        """An http or https URL; an fn: URL only for the import and staff kinds, which FN writes itself."""
        if url.startswith("fn:") and info.data.get("kind") in ("import", "staff"):
            return url
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"source url must be http or https: {url!r}")
        return url


def record_source(url: str, title: str, fields: list[tuple[str, object]], raw: dict, fetched_at: datetime,
                  source_date: str | None = None, *,
                  kind: Literal["record", "vendor_record", "staff"] = "record") -> tuple[Source, dict[str, tuple[int, int]]]:
    """A record Source (kind vendor_record for a vendor's answer) with one `path: value` line per field that has a value.

    Returns it with each line's offsets by path. The id holds the kind and the content hash, so a record
    whose text changed is stored as a new source.
    """
    lines, spans, at = [], {}, 0
    for path, value in fields:
        if value is None or value == "":
            continue
        line = normalize(f"{path}: {value}")
        spans[path] = (at, at + len(line))
        lines.append(line)
        at += len(line) + 1
    text = "\n".join(lines)
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    return Source(
        id=hashlib.sha1(f"{kind}\0{url}\0{content_hash}".encode()).hexdigest(), kind=kind, url=url, title=title,
        text=text, raw_json=json.dumps(raw, ensure_ascii=False, sort_keys=True), content_hash=content_hash,
        source_date=source_date, date_method="record_field" if source_date else None, fetched_at=fetched_at,
    ), spans


# One pass over vendor markdown: escapes, link and image text (one bracket level inside), then **, *, __, _ on a line.
MARKDOWN = re.compile(
    r"\\([!-/:-@\[-`{-~])"
    r"|!?\[((?:[^\[\]]|\[[^\]]*\])*)\]\((?:[^()]|\([^()]*\))*\)"
    r"|(\*\*|\*)(?=\S)(.+?)(?<=\S)\3(?!\*)"
    r"|(?<!\w)(__|_)(?=\S)(.+?)(?<=\S)\5(?!\w)"
)


def _plain(match: re.Match) -> str:
    escaped, anchor, _, starred, _, underscored = match.groups()
    if escaped is not None:
        return escaped
    return MARKDOWN.sub(_plain, next(g for g in (anchor, starred, underscored) if g is not None))


def page_source(url: str, title: str | None, markdown: str, raw: dict, fetched_at: datetime,
                source_date: str | None) -> Source:
    """A vendor_page Source whose text is the vendor's markdown as plain text, so a quote matches what the reader sees.

    Links keep their anchor text; emphasis marks, heading markers and backslash escapes go. The id holds the
    content hash, so a page whose text changed is stored as a new source.
    """
    text = normalize(MARKDOWN.sub(_plain, re.sub(r"^#{1,6}[ \t]+", "", markdown, flags=re.MULTILINE)))
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    return Source(
        id=hashlib.sha1(f"vendor_page\0{url}\0{content_hash}".encode()).hexdigest(), kind="vendor_page", url=url,
        title=" ".join(title.split()) or None if title else None, text=text,
        raw_json=json.dumps(raw, ensure_ascii=False, sort_keys=True),
        content_hash=content_hash, source_date=source_date, date_method="record_field" if source_date else None,
        fetched_at=fetched_at,
    )


class OrgFacts(Model):
    id: str
    name: str
    country_code: str | None = None
    region: str | None = None
    name_lang: str | None = None

    @field_validator("id")
    @classmethod
    def _id_form(cls, value: str) -> str:
        if not ORG_ID.fullmatch(value):
            raise ValueError(f"org id must be ror:<id>, wikidata:<Q> or openalex:<I>: {value!r}")
        return value


class Org(OrgFacts):
    source_id: str
    fetched_at: datetime


class Claim(Model):
    id: str
    person_id: str
    kind: ClaimKind
    relation: Relation | None = None
    org_id: str | None = None
    value: str
    quote: str
    quote_start: int
    quote_end: int
    source_id: str
    claim_date: str | None = None
    date_precision: DatePrecision | None = None
    date_method: DateMethod | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    # The calendar years the source lists for this claim, when it lists them.
    years: list[int] = []
    lat: float | None = None
    lon: float | None = None
    # When FN first stored the claim; empty on rows from before migration 006.
    first_seen_at: datetime | None = None
    rejected_at: datetime | None = None


class Person(Model):
    id: str
    display_name: str
    name_key: str
    list_status: ListStatus = "candidate"
    merged_into: str | None = None
    merged_at: datetime | None = None
    seen_at: datetime | None = None


class ClaimDraft(Model):
    person_id: str
    kind: ClaimKind
    relation: Relation | None = None
    org_id: str | None = None
    value: str
    quote: str
    quote_start: int
    quote_end: int
    source: Source
    claim_date: str | None = None
    date_precision: DatePrecision | None = None
    date_method: DateMethod | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    # The calendar years the source lists for this claim, when it lists them.
    years: list[int] = []
    lat: float | None = None
    lon: float | None = None

    @model_validator(mode="after")
    def _quote_at_offsets(self) -> "ClaimDraft":
        if not self.quote or not 0 <= self.quote_start < self.quote_end <= len(self.source.text):
            raise ValueError(f"empty quote or offsets [{self.quote_start}:{self.quote_end}] outside source {self.source.id}")
        found = self.source.text[self.quote_start:self.quote_end]
        if found != self.quote:
            raise ValueError(f"quote not at [{self.quote_start}:{self.quote_end}] of source {self.source.id}: {found!r}")
        return self


class Identifier(Model):
    scheme: IdentifierScheme
    value: str


# The extract task's answer: every person one part of a page names, with quotes the model copied from it.
class PageRelation(Model):
    relation: Relation
    org: str
    quote: str
    year_from: int | None = None
    year_to: int | None = None


class PageMention(Model):
    name: str
    quote: str
    role: str | None = None
    relations: list[PageRelation] = []


class PagePeople(Model):
    people: list[PageMention]


# A mention whose quotes were found in the page text: the cleaned name, its offsets and each kept relation's.
class Located(Model):
    name: str
    role: str | None = None
    span: Span
    relations: list[tuple[PageRelation, Span]] = []


class LaneHit(Model):
    person_id: str
    name_key: str
    lane: LaneName
    rank: int
    score: float
    matched_on: str
    claim_ids: list[str] = []


class Considered(Model):
    person_key: str
    name: str
    stage: str
    kept: bool
    reason: str


class MatchFlag(Model):
    person_id: str
    other_person_id: str
    reason: str
    shared_fact: str | None = None


class Entry(Model):
    name_key: str
    person_ids: list[str]
    # The records a lane hit, in person_ids order; records added only for a shared name are not in it and never score.
    hit_person_ids: list[str] = []
    lane_ranks: dict[LaneName, int]
    claim_ids: list[str] = []
    flag: str | None = None


class ScorePart(Model):
    feature: LaneName | Literal["belgian_years"]
    rank: int
    points: float
    claim_ids: list[str] = []
    detail: str = ""


class Candidate(Model):
    search_id: str
    person_id: str
    person_ids: list[str]
    section: Section
    rank: int
    score: float
    lane_ranks: dict[LaneName, int]
    reason_claim_ids: list[str] = []
    score_parts: list[ScorePart] = []
    hit_person_ids: list[str] = []
    cut_reason: CutReason | None = None


# One staff decision; detail holds what undo needs, ids and never contact values.
class Event(Model):
    id: str
    at: datetime
    kind: EventKind
    person_id: str | None = None
    other_person_id: str | None = None
    search_id: str | None = None
    rank: int | None = None
    section: Section | None = None
    import_id: str | None = None
    claim_id: str | None = None
    undoes: str | None = None
    detail: dict[str, Any] = {}
    user_id: None = None


# How a person reads on every staff page; present.py builds these and web/parts.py turns them into HTML.
class QuoteView(Model):
    text: str
    label: str
    href: str
    date: str


class ClaimView(Model):
    claim_id: str
    kind: ClaimKind
    what: str
    years: str = ""
    quote: QuoteView | None = None
    label: str
    href: str
    date: str
    is_new: bool = False


class OrgView(Model):
    org: str
    years: str = ""


class PersonView(Model):
    person_id: str
    name: str
    role: str | None = None
    employer: str | None = None
    place: str | None = None
    lat: float | None = None
    lon: float | None = None
    orgs: list[OrgView] = []
    more_orgs: int = 0
    evidence: ClaimView | None = None
    status: ListStatus = "candidate"
    added: str | None = None
    new_facts: int = 0
    email: str | None = None
    phone: str | None = None


class ResultsView(Model):
    network: list[PersonView] = []
    new: list[PersonView] = []


class StepRun(Model):
    id: str
    search_id: str
    seq: int
    step: str
    status: StepStatus
    started_at: datetime
    ended_at: datetime | None = None
    input_model: str
    output_model: str | None = None
    contracts_version: str = CONTRACTS_VERSION
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    model: str | None = None
    prompt_sha: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    traceback: str | None = None
    log: str = ""


class StepCall(Model):
    step_run_id: str
    seq: int
    kind: CallKind
    request: str
    status: int | None = None
    duration_ms: int
    response_sha: str | None = None
    response_path: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    error: str | None = None


class RequestError(Model):
    id: str
    route: str
    traceback: str
    at: datetime


class GeoArea(Model):
    place: str
    city: str
    lat: float
    lon: float
    radius_km: float


class LLMResult[T](Model):
    value: T
    model: str
    cost_usd: float
    tokens_in: int
    tokens_out: int
    billing: str


# Step models, in the order search.py runs them: parse, lane:<name> per lane with publish between, resolve, rank, save.
class ParseIn(Model):
    question: str


class ParseOut(Model):
    chips: Chips


class LaneIn(Model):
    search_id: str
    chips: Chips
    depth: Depth = "quick"


class LaneOut(Model):
    lane: LaneName
    query: str
    total_seen: int
    hits: list[LaneHit] = []
    considered: list[Considered] = []


class ResolveIn(Model):
    outs: list[LaneOut]


class ResolveOut(Model):
    entries: list[Entry]
    flags: list[MatchFlag] = []


class RankIn(Model):
    entries: list[Entry]
    chips: Chips


class RankOut(Model):
    candidates: list[Candidate]


class SaveIn(Model):
    candidates: list[Candidate]
    flags: list[MatchFlag] = []


class SaveOut(Model):
    count: int


# The publish step after each lane but the last, and how far a search is.
class PublishIn(Model):
    # The lanes whose outputs are published; the outputs themselves are on the lanes' own step rows.
    lanes: list[LaneName]
    chips: Chips


class PublishOut(Model):
    count: int


class SearchProgress(Model):
    status: SearchStatus
    people: int
    version: int


# The one step of the fn-orgs job.
class OrgsIn(Model):
    ids: list[str]


class OrgsOut(Model):
    orgs: list[Org]


class GoldPick(Model):
    case_id: str
    name: str
    gold_tie: GoldTie
    openalex_id: str | None = None
    reachable: bool | None = None
    reach_evidence: str = ""


class GoldCase(Model):
    id: str
    question: str
    source_url: str | None = None
    picks: list[GoldPick]


class PickResult(Model):
    case_id: str
    name: str
    verdict: PickVerdict
    section: Section | None = None
    rank: int | None = None
    gold_tie: GoldTie
    belgian: str = ""
    lanes: str = ""
    lost_step: str = ""
    lost_reason: str = ""


class TopCard(Model):
    position: int
    section: Section
    rank: int
    name: str
    lanes: str
    quote: str
    belgian: str


class CaseResult(Model):
    case_id: str
    group: GoldGroup
    question: str
    chips: str
    search_id: str
    status: SearchStatus
    http_cost_usd: float = 0.0
    llm_cost_usd: float = 0.0
    picks: list[PickResult]
    top: list[TopCard]
    failed_lanes: list[str] = []
