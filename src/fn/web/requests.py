"""Request helpers both routers use: the store and worker of the app and the fields of a posted form."""
from urllib.parse import parse_qs

from fastapi import Request

from fn.store import Store
from fn.worker import Worker


def store_of(request: Request) -> Store:
    return request.app.state.store


def worker_of(request: Request) -> Worker:
    return request.app.state.worker


async def form_of(request: Request) -> dict[str, list[str]]:
    return parse_qs((await request.body()).decode(errors="replace"), keep_blank_values=True)


def first(form: dict[str, list[str]], name: str) -> str:
    return " ".join(form.get(name, [""])[0].split())
