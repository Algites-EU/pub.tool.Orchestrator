from __future__ import annotations

import re

from orchestrator.common.errors import ConfigurationValidationError

_PATTERN = re.compile(r"^([1-9][0-9]*)(B|kB|MB|GB|TB|PB|KiB|MiB|GiB|TiB|PiB)$")
_DECIMAL = {"B": 1, "kB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4, "PB": 1000**5}
_BINARY = {"KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4, "PiB": 1024**5}


def size_to_bytes(value: str) -> int:
    match = _PATTERN.match(value)
    if not match:
        raise ConfigurationValidationError(f"Invalid data size '{value}'.")
    amount = int(match.group(1))
    unit = match.group(2)
    return amount * (_DECIMAL.get(unit) or _BINARY[unit])
