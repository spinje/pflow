"""Human-readable duration formatting.

`format_duration(ms)` renders milliseconds as a short human-readable string
for dry-run estimates and other descriptive contexts. For live-progress
rendering, `core/output_controller.py` uses a tighter inline `:.1f}s` format
by design — keep the two formats distinct.
"""

from __future__ import annotations

_MS_PER_SECOND = 1000.0
_MS_PER_MINUTE = 60_000.0
_MS_PER_HOUR = 3_600_000.0


def format_duration(ms: float) -> str:
    """Render a millisecond duration as a short human-readable string.

    Breakpoints:
    - < 1s:  `450ms`
    - < 1m:  `2.3s`
    - < 1h:  `3m12s`
    - >= 1h: `1h5m`

    Negative or NaN inputs are treated as zero. Callers that want to elide
    sub-threshold values entirely (e.g. suppress < 1s in text output) should
    do so before calling this — the formatter always renders something.
    """
    if ms != ms or ms < 0:  # NaN or negative
        ms = 0.0

    if ms < _MS_PER_SECOND:
        return f"{round(ms)}ms"

    if ms < _MS_PER_MINUTE:
        return f"{ms / _MS_PER_SECOND:.1f}s"

    if ms < _MS_PER_HOUR:
        minutes = int(ms // _MS_PER_MINUTE)
        seconds = round((ms - minutes * _MS_PER_MINUTE) / _MS_PER_SECOND)
        if seconds == 60:
            minutes += 1
            seconds = 0
        if minutes < 60:
            return f"{minutes}m{seconds}s"
        # Carry crossed into the hour bucket — fall through to hour rendering.

    hours = int(ms // _MS_PER_HOUR)
    minutes = round((ms - hours * _MS_PER_HOUR) / _MS_PER_MINUTE)
    if minutes == 60:
        hours += 1
        minutes = 0
    return f"{hours}h{minutes}m"
