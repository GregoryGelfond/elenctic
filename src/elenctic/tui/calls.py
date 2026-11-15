"""The library calls the interactive view makes off its own thread, and how each one is stopped.

A session keeps the interrupt it was opened with, and each of the view's calls runs on a thread of
its own; so the interrupt the view gives the library asks the thread which call it is making.
"""

from collections.abc import Callable
from threading import Event, local
from typing import override

from elenctic.search import Interrupt

_making = local()


class Calls(Interrupt):
    """An interrupt pulled for every call, or for the one call the asking thread is making."""

    @property
    @override
    def pulled(self) -> bool:
        stop: Event | None = getattr(_making, "stop", None)
        return super().pulled or (stop is not None and stop.is_set())


def call[Found](work: Callable[[], Found], stop: Event) -> Found:
    """Make a library call on this thread, which `stop` ends at the search's next slice."""
    _making.stop = stop
    try:
        return work()
    finally:
        del _making.stop
