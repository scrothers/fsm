"""HTTP helper: ``urlopen`` with an explicit User-Agent.

factorio.com and the mod portal reject the default ``Python-urllib`` User-Agent
with HTTP 403, so every request the manager makes must set one. Centralizing it
here keeps the header consistent and the call sites monkeypatchable in tests.
"""

from __future__ import annotations

import urllib.request

from . import __version__

USER_AGENT = f"factorio-server-manager/{__version__}"

#: Default network timeout (seconds); callers may override per request.
DEFAULT_TIMEOUT = 30


def urlopen(url: str, *, timeout: int = DEFAULT_TIMEOUT):
    """Open a URL with the manager's User-Agent and a timeout.

    :returns: the ``http.client.HTTPResponse`` (usable as a context manager).
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310
