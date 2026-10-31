"""Every value that crosses a module boundary in fn."""
import re
import unicodedata
from datetime import datetime
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

CONTRACTS_VERSION = "1"
NORMALIZE_VERSION = 1

TieType = Literal["flemish", "belgian", "dutch", "none_found"]
ListStatus = Literal["candidate", "in_list", "skipped"]
Section = Literal["network", "new"]
ClaimKind = Literal["topic", "affiliation", "role", "location", "availability"]
Relation = Literal[
    "studied_at", "works_at", "worked_at", "affiliated_with", "hosted_by",
    "fellow_of", "member_of", "consul_for", "born_in", "lives_in",
]
DateMethod = Literal[
    "page_date", "sitemap", "wayback_first_seen", "document_heading",
    "record_field", "read_date", "sheet_date", "staff_edit",
]
DatePrecision = Literal["year", "month", "day"]
SourceKind = Literal["page", "record", "seed_page", "import", "vendor_record"]
StepStatus = Literal["running", "ok", "error", "skipped", "interrupted"]
SearchStatus = Literal["queued", "running", "done", "failed", "interrupted"]
LaneName = Literal["seeds", "openalex"]
ChipOrigin = Literal["parsed", "edited"]
Depth = Literal["quick"]
IdentifierScheme = Literal["seed", "openalex", "orcid", "profile_url"]
Ask = Literal["talk", "mentor", "host", "join", "other"]
PlaceKind = Literal["metro", "anywhere_us", "abroad"]
CallKind = Literal["http", "llm"]
LLMMode = Literal["live", "record", "replay"]
GoldTie = Literal["flemish", "belgian", "none", "unverified"]
PickVerdict = Literal["found", "missed", "no lane in slice"]
GoldGroup = Literal["dev", "held-out", "other"]


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


class HttpClient(Protocol):
    def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response: ...


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
    def _http_only(cls, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"source url must be http or https: {url!r}")
        return url


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
    lat: float | None = None
    lon: float | None = None


class Person(Model):
    id: str
    display_name: str
    name_key: str
    list_status: ListStatus = "candidate"
    merged_into: None = None


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


class TieLabel(Model):
    tie: TieType
    claim_ids: list[str] = []
    checked: list[str] = []
    rules_version: str


class MatchFlag(Model):
    person_id: str
    other_person_id: str
    reason: str
    shared_fact: str | None = None


class Entry(Model):
    name_key: str
    person_ids: list[str]
    lane_ranks: dict[LaneName, int]
    claim_ids: list[str] = []
    flag: str | None = None


class Candidate(Model):
    search_id: str
    person_id: str
    person_ids: list[str]
    section: Section
    rank: int
    score: float
    lane_ranks: dict[LaneName, int]
    reason_claim_ids: list[str] = []
    tie: TieLabel


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


# Step models, in the order search.py runs them: parse, lane:<name> per lane, tie, resolve, rank, save.
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


class TieIn(Model):
    search_id: str
    person_ids: list[str]


class TieOut(Model):
    labels: dict[str, TieLabel]


class ResolveIn(Model):
    outs: list[LaneOut]


class ResolveOut(Model):
    entries: list[Entry]
    flags: list[MatchFlag] = []


class RankIn(Model):
    entries: list[Entry]
    labels: dict[str, TieLabel]
    chips: Chips


class RankOut(Model):
    candidates: list[Candidate]


class SaveIn(Model):
    candidates: list[Candidate]
    flags: list[MatchFlag] = []


class SaveOut(Model):
    count: int


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
    picks: list[GoldPick]


class PickResult(Model):
    case_id: str
    name: str
    verdict: PickVerdict
    section: Section | None = None
    rank: int | None = None
    gold_tie: GoldTie
    tie: TieType | None = None
    tie_agrees: bool | None = None
    lost_step: str = ""
    lost_reason: str = ""


class TopCard(Model):
    position: int
    section: Section
    rank: int
    name: str
    lanes: str
    quote: str
    tie: TieType


class CaseResult(Model):
    case_id: str
    group: GoldGroup
    question: str
    chips: str
    search_id: str
    status: SearchStatus
    picks: list[PickResult]
    top: list[TopCard]
