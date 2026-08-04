"""
Small CLI helpers shared by the runnable scripts.

`clean_argv` strips a pasted shell-style comment from the command line. On
Windows `cmd`, '#' is NOT a comment character, so a command copied with a
trailing "  # note" is passed to the program as arguments and argparse rejects
it. Dropping everything from the first '#' token onward makes every script
tolerant of that, while still validating real flags strictly.
"""
from __future__ import annotations

import sys


def clean_argv(argv: list[str] | None = None) -> list[str]:
    argv = list(sys.argv[1:] if argv is None else argv)
    cut = next((i for i, a in enumerate(argv) if a.startswith("#")), len(argv))
    return argv[:cut]
