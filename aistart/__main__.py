from __future__ import print_function

import sys

if sys.version_info < (3, 10):
    print(
        "aistart requires Python 3.10 or newer. "
        "Run it with python3 -m aistart, or install it with pip from Python 3.",
        file=sys.stderr,
    )
    raise SystemExit(1)

from .cli import run

run()
