from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

from .errors import CliArgumentError, OutputWriteError


def resolve_output_path(file_name: str | None, output_folder: str | None) -> Path | None:
    if file_name is None:
        return None
    path = Path(file_name).expanduser()
    if path.is_absolute():
        return path
    base = Path(output_folder).expanduser() if output_folder else Path.cwd()
    return base / path


def serialize_document(document: Any, output_format: str) -> str:
    if output_format == "yaml":
        return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    if output_format == "json":
        return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    raise CliArgumentError(f"Unsupported output format '{output_format}'.")


def _atomic_write(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            handle.write(text)
            temp_name = handle.name
        os.replace(temp_name, path)
    except OSError as exc:
        raise OutputWriteError(f"Cannot write output file '{path}': {exc}") from exc


def write_result(document: Any, output_format: str, output_path: Path | None) -> None:
    text = serialize_document(document, output_format)
    if output_path is None:
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except OSError as exc:
            raise OutputWriteError(f"Cannot write result to stdout: {exc}") from exc
    else:
        _atomic_write(output_path, text)
