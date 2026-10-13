"""Whether a path exists, in three outcomes, so a path that cannot be checked never reads as absent.

``Path.exists()`` and ``Path.is_file()`` swallow ``OSError`` on Python 3.14 and raise it on 3.10-3.13. A
permission fault or an unmounted volume would then read as "deleted" (or crash). A decision that deletes,
hides or falls back to defaults on "absent" asks ``path_state`` instead.
"""

from __future__ import annotations

import os
from typing import Literal

PathState = Literal["present", "absent", "unknown"]


def path_state(path: str | os.PathLike[str]) -> PathState:
    """``present``: ``os.stat`` succeeds. ``absent``: there is no directory entry at the path, not even a
    dangling symlink (a path with a NUL byte names nothing either). ``unknown``: anything else, such as a
    permission fault or a symlink whose target is unavailable."""
    try:
        os.stat(path)
    except ValueError:
        return "absent"
    except (FileNotFoundError, NotADirectoryError):
        pass
    except OSError:
        return "unknown"
    else:
        return "present"
    try:
        os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return "absent"
    except OSError:
        return "unknown"
    return "unknown"  # an entry whose target is unavailable (a dangling symlink)
