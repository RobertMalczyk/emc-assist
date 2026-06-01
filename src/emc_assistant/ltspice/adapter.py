"""Local LTspice adapter — detection and batch command construction.

LTspice is never bundled with the application. The user must have a
local installation. MVP supports ``dry-run`` (command only) and
prepares for ``local-run`` (M1).
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


COMMON_WINDOWS_PATHS = (
    r"C:\Program Files\LTC\LTspiceXVII\XVIIx64.exe",
    r"C:\Program Files\ADI\LTspice\LTspice.exe",
    r"C:\Program Files (x86)\LTC\LTspiceXVII\XVIIx64.exe",
)
COMMON_UNIX_NAMES = ("LTspice", "ltspice", "XVIIx64.exe")


def discover_ltspice(configured_path: str | None = None) -> Path | None:
    """Try to find a local LTspice installation.

    Resolution order:
    1) explicit configured path,
    2) ``LTSPICE_PATH`` environment variable,
    3) common Windows installation paths,
    4) ``shutil.which`` for typical Unix names.
    """
    if configured_path:
        p = Path(configured_path)
        if p.is_file():
            return p

    env_path = os.environ.get("LTSPICE_PATH")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return p

    for candidate in COMMON_WINDOWS_PATHS:
        p = Path(candidate)
        if p.is_file():
            return p

    for name in COMMON_UNIX_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)

    return None


@dataclass
class LtspiceAdapter:
    executable: Path | None
    timeout_seconds: int = 120

    @property
    def available(self) -> bool:
        return self.executable is not None and self.executable.is_file()

    def build_command(self, netlist: Path) -> list[str]:
        exe = str(self.executable) if self.executable else "<ltspice-not-found>"
        return [exe, "-b", "-Run", str(netlist)]
