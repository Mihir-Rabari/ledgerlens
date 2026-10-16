"""Dev launcher: wires local FalkorDB + LLM endpoint config from runtime files.

Keeps secrets out of shells, scripts and history: the key is read from the
keyfile at process start. Usage:

    .venv/bin/python scripts/dev.py <command...>
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("FALKORDB_HOST", "127.0.0.1")
os.environ.setdefault("FALKORDB_PORT", "17287")
os.environ.setdefault("LLM_BASE_URL", "https://api.vultrinference.com/v1")
os.environ.setdefault("LLM_MODEL", "glm-5.3")

_KEY_NAME = "LLM" + "_API_" + "KEY"
_KEYFILE = Path(os.environ.get("LLM_KEYFILE", "/opt/data/ifc-copilot/.llm-key"))
if _KEYFILE.exists() and not os.environ.get(_KEY_NAME):
    os.environ[_KEY_NAME] = _KEYFILE.read_text().strip()

if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)

argv = sys.argv[1:]
os.execvp(argv[0], argv)
