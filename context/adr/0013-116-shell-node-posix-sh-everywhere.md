# Shell node means POSIX sh on every platform — Git Bash supplies it on Windows

The shell node's dialect is part of its contract, not a platform detail. Today `shell=True` gives `/bin/sh` on Unix (POSIX sh); on Windows it would silently give `cmd.exe`, changing what every command string *means*. For Windows support (Task 116) we decided: a shell step means POSIX sh everywhere — on win32, commands run through Git Bash (resolved deliberately from its known install locations / via `git`, **never** naive `which("bash")`), with a structured error telling users to install Git for Windows when absent. Agents are pflow's primary workflow authors and LLMs emit POSIX shell by default; a platform-dependent dialect would make agent-generated workflows wrong-by-default on Windows and can never later be unified without breaking one platform's installed workflows.

## Considered Options

- **cmd.exe (native `shell=True`)** — zero dependencies, but forks the contract per-platform forever, breaks agent-authored commands by default, and would force skip-marking ~37% of the test suite (141 files use POSIX commands as generic fixtures) or rewriting ~1,000 tests.
- **PowerShell** — same platform fork plus a third quoting/semantics dialect.
- **Git Bash (chosen)** — one dialect everywhere; preinstalled on GitHub `windows-latest` runners; ships with Git for Windows, which most Windows developers already have.

## Consequences

- **Default is forever; dialects are additive.** If Windows-native shells are ever wanted, they must arrive as an opt-in per-step parameter — never by changing what an unadorned shell step means.
- **WSL trap:** on end-user machines `which("bash")` can resolve `C:\Windows\System32\bash.exe` (WSL — a Linux VM with a different filesystem), while Git Bash's `bash.exe` is often *not* on PATH. CI can't catch this (runners put Git Bash on PATH), so resolution must be explicit or user behavior diverges from green CI.
- **MSYS path mangling:** Git Bash rewrites POSIX-looking absolute path arguments (`/foo` → `C:\Program Files\Git\foo`); a known, documented limitation.
- Windows users without Git for Windows get a clear install-guidance error, not a working shell node.
- Strictly, the contract is POSIX *sh* (what `/bin/sh` provides), not bash: bashisms already work on macOS but fail on dash-based Linux, and that asymmetry carries over unchanged.
