"""Runs the tracing pipeline off the Tk main thread.

Tracing a large photo takes long enough to freeze the UI mid-drag, so every
run happens on a background thread and the result is handed back through a
queue that Tk polls. Requests are debounced and superseded: while a slider is
moving only the latest parameter set matters, so older ones are dropped
rather than queued up behind it.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..params import TraceParams
from ..pipeline import TraceResult, run

#: Milliseconds of quiet before a parameter change triggers a re-trace.
DEBOUNCE_MS = 150

#: How often Tk checks the result queue.
POLL_MS = 40


@dataclass(slots=True)
class _Job:
    token: int
    image: np.ndarray
    params: TraceParams


class TraceWorker:
    """Debounced, single-flight pipeline runner bound to a Tk widget."""

    def __init__(
        self,
        widget,
        on_result: Callable[[TraceResult, TraceParams], None],
        on_error: Callable[[Exception], None],
        on_busy: Callable[[bool], None] | None = None,
    ) -> None:
        self._widget = widget
        self._on_result = on_result
        self._on_error = on_error
        self._on_busy = on_busy
        self._busy = False
        self._results: queue.Queue = queue.Queue()
        self._pending: _Job | None = None
        self._debounce_id: str | None = None
        self._token = 0
        self._lock = threading.Lock()
        self._widget.after(POLL_MS, self._drain)

    def request(self, image: np.ndarray | None, params: TraceParams) -> None:
        """Schedule a trace, replacing any request not yet started."""
        if image is None:
            return
        with self._lock:
            self._token += 1
            self._pending = _Job(self._token, image, params)
        if self._debounce_id is not None:
            self._widget.after_cancel(self._debounce_id)
        self._debounce_id = self._widget.after(DEBOUNCE_MS, self._start)

    def _start(self) -> None:
        self._debounce_id = None
        with self._lock:
            job = self._pending
            self._pending = None
        if job is None:
            return
        self._set_busy(True)
        threading.Thread(target=self._run, args=(job,), daemon=True).start()

    def _run(self, job: _Job) -> None:
        try:
            result = run(job.image, job.params)
            self._results.put((job.token, job.params, result, None))
        except Exception as exc:  # surfaced in the status bar, not a crash
            self._results.put((job.token, job.params, None, exc))

    def _drain(self) -> None:
        """Deliver the newest finished result and discard stale ones."""
        latest = None
        try:
            while True:
                latest = self._results.get_nowait()
        except queue.Empty:
            pass

        if latest is not None:
            token, params, result, error = latest
            # A newer request has already been issued; this one is obsolete.
            if token >= self._token:
                self._set_busy(False)
                if error is not None:
                    self._on_error(error)
                else:
                    self._on_result(result, params)

        self._widget.after(POLL_MS, self._drain)

    def _set_busy(self, busy: bool) -> None:
        """Report start and finish once each, not per superseded job.

        A dragged slider fires many jobs; the indicator should stay on for the
        whole drag rather than flickering between them.
        """
        if busy == self._busy:
            return
        self._busy = busy
        if self._on_busy is not None:
            self._on_busy(busy)
