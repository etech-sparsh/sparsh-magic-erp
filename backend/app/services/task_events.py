"""In-process pub/sub for real-time task updates over SSE.

Single-process only (no Redis) — sufficient for the current single-uvicorn deployment.
Each connected client (identified by user_id) gets an asyncio.Queue; task mutation
endpoints call `publish(recipients, event)` to fan an event out to the right users'
open streams. Reuses the SSE (text/event-stream) approach already used by the assistant.
"""
import asyncio
from typing import Dict, Set, Iterable, Optional

# user_id -> set of live queues (a user may have multiple tabs/streams open)
_subscribers: Dict[str, Set[asyncio.Queue]] = {}


def subscribe(user_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.setdefault(user_id, set()).add(q)
    return q


def unsubscribe(user_id: str, q: asyncio.Queue) -> None:
    conns = _subscribers.get(user_id)
    if not conns:
        return
    conns.discard(q)
    if not conns:
        _subscribers.pop(user_id, None)


async def publish(user_ids: Iterable[Optional[str]], event: dict) -> None:
    """Deliver `event` to every open stream belonging to any of `user_ids`.
    Silently skips users with no open stream and never raises into the caller."""
    seen: Set[str] = set()
    for uid in user_ids:
        if not uid or uid in seen:
            continue
        seen.add(uid)
        for q in list(_subscribers.get(uid, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow/stuck consumer — drop rather than block the mutation


def recipients_for(task_doc: dict) -> Set[str]:
    """Users who should be notified about a task change: creator + assignees + watchers."""
    ids: Set[str] = set()
    creator = task_doc.get("user_id")
    if creator:
        ids.add(str(creator))
    for uid in (task_doc.get("target_staff_id") or []):
        if uid:
            ids.add(str(uid))
    for uid in (task_doc.get("watchers") or []):
        if uid:
            ids.add(str(uid))
    return ids
