"""Wake Dispatch backend logic (stdlib only, Python 3.11).

``main.Plugin`` is a thin adapter over these modules:

- ``mac``: MAC / SecureOn normalisation with plain-language errors.
- ``packet``: magic packet construction and UDP broadcast sending.
- ``storage``: atomic JSON files, schema migration, corrupt-file quarantine.
- ``devices``: device validation, id generation, import / export / merge.
- ``netinfo``: default route, interface state, ARP neighbours, status checks.
- ``dispatch``: the ``Dispatcher`` (gating, bursts, records, error mapping).
- ``automation``: boot gate and resume watcher.
- ``updates``: the once-a-day check for a newer release on GitHub.
"""

MODULES = (
    "log",
    "mac",
    "packet",
    "storage",
    "devices",
    "netinfo",
    "dispatch",
    "automation",
    "updates",
)
