"""Make the shared ``infrahub_solution_ai_dc`` package importable from the repository checkout.

Infrahub imports this directory as ``commits.<sha>.<directory>.<module>`` and puts the repository's own
directory on ``sys.path``, not the checkout. ``src/`` is therefore not on the path, and an Infrahub image
without the package installed fails with ``ModuleNotFoundError``. This appends ``src/`` after any installed
copy, so a custom image that already holds the package keeps using it.

The package is imported once per process under its plain name: the first checkout that imports it supplies it
to every later one.
"""

import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parent.parent / "src")  # noqa: RUF067
if _SRC not in sys.path:  # noqa: RUF067
    sys.path.append(_SRC)
