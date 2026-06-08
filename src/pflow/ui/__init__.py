"""pflow web UI — a local server that serves a React Flow view of a workflow.

Shipped behind the ``pflow[ui]`` extra. ``server.py`` (and its Starlette import)
is loaded lazily by the ``pflow ui`` command, so a base install without the
extra never pays for — or fails on — the web-stack imports.
"""
