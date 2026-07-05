"""Factorio server manager.

A single Python package that manages multiple isolated Factorio headless
servers on a host, driven by systemd user template units. The ``fsm`` console
script runs on the server; ``factorio_server_manager.deploy`` runs on a workstation to
push the source and install the unit over ssh/rsync.
"""

__version__ = "1.0.0"
