"""Progress tracker + SSE broadcast."""
from __future__ import annotations
import asyncio
import json
from dataclasses import dataclass, field


@dataclass
class ProgressEvent:
    job_id: str
    event_type: str
    data: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({"type": self.event_type, "job_id": self.job_id, "data": self.data})


class ProgressTracker:
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._subs: dict[str, list[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def create_job(self, jid: str, total: int = 0):
        async with self._lock:
            self._jobs[jid] = {
                "status": "CREATED",
                "progress": 0,
                "total": total,
                "crawled": 0,
                "analyzed": 0,
                "current_url": "",
            }
            self._subs[jid] = []

    async def update(self, jid: str, **kw):
        async with self._lock:
            j = self._jobs.get(jid)
            if not j:
                return
            # Extract event_type BEFORE updating state to avoid polluting it
            event_type = kw.pop("event_type", "PROGRESS")
            j.update(kw)
            ev = ProgressEvent(job_id=jid, event_type=event_type, data={k: v for k, v in j.items()})
            dead: list[asyncio.Queue] = []
            for q in self._subs.get(jid, []):
                try:
                    q.put_nowait(ev)
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                self._subs[jid].remove(q)

    async def subscribe(self, jid: str) -> asyncio.Queue:
        async with self._lock:
            if jid not in self._subs:
                self._subs[jid] = []
            q: asyncio.Queue = asyncio.Queue(maxsize=0)
            self._subs[jid].append(q)
            j = self._jobs.get(jid)
            if j:
                q.put_nowait(ProgressEvent(job_id=jid, event_type="STATUS", data=dict(j)))
            return q

    async def unsubscribe(self, jid: str, q: asyncio.Queue):
        async with self._lock:
            s = self._subs.get(jid, [])
            if q in s:
                s.remove(q)

    def get_state(self, jid: str) -> dict | None:
        return self._jobs.get(jid)


tracker = ProgressTracker()