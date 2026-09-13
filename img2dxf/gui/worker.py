"""Runs the tracing pipeline off the Tk main thread.

Tracing a large photo takes long enough to freeze the UI mid-drag, so every
run happens on a background thread and the result is handed back through a
queue that Tk polls. Requests are debounced and superseded: while a slider is
moving only the latest parameter set matters, so older ones are dropped
rather than queued up behind it.
"""

from __future__ import annotations

import contextlib
import gc
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..params import TraceParams
from ..pipeline import TraceResult, run

#: Milliseconds of quiet before a parameter change triggers a re-trace.
DEBOUNCE_MS = 150

#: How often Tk checks the result queue.
POLL_MS = 40


@contextlib.contextmanager
def _no_garbage_collection():
    """Keep the collector from running while this thread traces.

    A collection triggered here runs finalizers on *this* thread, and Tk's
    `Variable.__del__` calls into Tcl. Tkinter is not thread-safe, so that
    call deadlocks against the main loop and the app freezes mid-trace with
    the progress bar still spinning — an intermittent hang that looks like
    the pipeline hung, and is nothing to do with it.

    A trace is short and its arrays are freed by reference counting, so the
    pause costs nothing measurable.
    """
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()


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
        self._stopped = False
        self._poll_id: str | None = None
        self._schedule_poll()

    def stop(self) -> None:
        """Stop polling, so nothing is left scheduled against a dead widget.

        Tk raises "invalid command name" if an ``after`` callback fires after
        its widget is destroyed, which surfaces as a spurious error on exit.
        """
        self._stopped = True
        for pending in (self._poll_id, self._debounce_id):
            if pending is not None:
                try:
                    self._widget.after_cancel(pending)
                except tk.TclError:
                    pass
        self._poll_id = self._debounce_id = None

    def _schedule_poll(self) -> None:
        if self._stopped:
            return
        try:
            self._poll_id = self._widget.after(POLL_MS, self._drain)
        except tk.TclError:
            # The widget is already gone; nothing left to poll for.
            self._stopped = True

    def request(self, image: np.ndarray | None, params: TraceParams) -> None:
        """Schedule a trace, replacing any request not yet started."""
        if image is None or self._stopped:
            return
        with self._lock:
            self._token += 1
            self._pending = _Job(self._token, image, params)
        if self._debounce_id is not None:
            self._widget.after_cancel(self._debounce_id)
        self._debounce_id = self._widget.after(DEBOUNCE_MS, self._start)

    def _start(self) -> None:
        self._debounce_id = None
        if self._stopped:
            return
        with self._lock:
            job = self._pending
            self._pending = None
        if job is None:
            return
        self._set_busy(True)
        threading.Thread(target=self._run, args=(job,), daemon=True).start()

    def _run(self, job: _Job) -> None:
        with _no_garbage_collection():
            try:
                result = run(job.image, job.params)
                self._results.put((job.token, job.params, result, None))
            except Exception as exc:  # surfaced in the status bar, not a crash
                self._results.put((job.token, job.params, None, exc))

    def _drain(self) -> None:
        """Deliver the newest finished result and discard stale ones."""
        self._poll_id = None
        if self._stopped:
            return

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

        self._schedule_poll()

    def _set_busy(self, busy: bool) -> None:
        """Report start and finish once each, not per superseded job.

        A dragged slider fires many jobs; the indicator should stay on for the
        whole drag rather than flickering between them.
        """
        if busy == self._busy or self._stopped:
            return
        self._busy = busy
        if self._on_busy is not None:
            self._on_busy(busy)
