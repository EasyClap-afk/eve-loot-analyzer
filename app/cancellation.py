"""Cooperative analysis cancellation, including requests awaiting ESI."""
import asyncio
from contextvars import ContextVar
import httpx


class AnalysisCancelled(BaseException):
    # Market/industry fallbacks catch Exception; cancellation must pass through.
    pass


_current = ContextVar('analysis_cancellation', default=None)


def check_cancelled():
    scope = _current.get()
    if scope is not None and scope.event.is_set():
        raise AnalysisCancelled()


def request(client, path, **kwargs):
    check_cancelled()
    scope = _current.get()
    if scope is None:
        return client.get(path, **kwargs)
    return scope.runner.run(scope.get(client, path, **kwargs))


class CancellationScope:
    def __init__(self, event):
        self.event = event
        self.runner = asyncio.Runner()
        self.clients = {}

    def __enter__(self):
        self.token = _current.set(self)
        return self

    async def get(self, client, path, **kwargs):
        if client not in self.clients:
            self.clients[client] = httpx.AsyncClient(
                base_url=client.base_url, headers=client.headers,
                timeout=client.timeout, follow_redirects=client.follow_redirects)
        task = asyncio.create_task(self.clients[client].get(path, **kwargs))
        try:
            while not task.done():
                check_cancelled()
                await asyncio.wait({task}, timeout=0.05)
            check_cancelled()
            return task.result()
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def __exit__(self, *exc):
        async def close():
            for client in self.clients.values():
                await client.aclose()
        try:
            if self.clients:
                self.runner.run(close())
        finally:
            self.runner.close()
            _current.reset(self.token)
