"""The lane contract and the registry search.py runs, one step lane:<name> per lane."""
from typing import Protocol

from fn.contracts import LaneIn, LaneName, LaneOut
from fn.lanes import linkedin, openalex, seeds, web
from fn.steps import StepContext


class Lane(Protocol):
    name: LaneName

    def run(self, ctx: StepContext, inp: LaneIn) -> LaneOut: ...


LANES: list[Lane] = [seeds, openalex, web, linkedin]
