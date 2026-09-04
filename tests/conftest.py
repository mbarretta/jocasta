"""Shared pytest configuration.

Puts the repo's ``scripts/`` directory on ``sys.path`` so tests can import the
validator and helper modules directly (``import validate``, ``import
jocasta_common``) without packaging them. The directory may not exist yet in a
fresh checkout; inserting the path is harmless either way.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
