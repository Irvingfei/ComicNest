"""ComicNest backend package."""

import os
import sys

_VENDOR_PYTHON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor", "python"
)
if os.path.isdir(_VENDOR_PYTHON) and _VENDOR_PYTHON not in sys.path:
    sys.path.append(_VENDOR_PYTHON)

__version__ = "1.0.006"
