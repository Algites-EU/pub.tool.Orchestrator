from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from xml.etree import ElementTree as ET

import yaml

from .errors import CliArgumentError, OutputWriteError


_XML_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


def resolve_output_path(file_name: str | None, output_folder: str | None) -> Path | None:
    if file_name is None:
        return None
    path = Path(file_name).expanduser()
    if path.is_absolute():
        return path
    base = Path(output_folder).expanduser() if output_folder else Path.cwd()
    return base / path


def _xml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _append_xml_value(parent: ET.Element, value: Any) -> None:
    if isinstance(value, dict):
        for key, child_value in value.items():
            key = str(key)
            if not _XML_NAME.match(key):
                raise CliArgumentError(
                    f"Cannot serialize mapping key '{key}' as XML element name."
                )
            child = ET.SubElement(parent, key)
            _append_xml_value(child, child_value)
        return
    if isinstance(value, list):
        for item in value:
            child = ET.SubElement(parent, "item")
            _append_xml_value(child, item)
        return
    parent.text = _xml_scalar(value)


def serialize_xml(document: Any, root_name: str) -> str:
    if not _XML_NAME.match(root_name):
        raise CliArgumentError(f"Invalid XML root element name '{root_name}'.")
    root = ET.Element(root_name)
    _append_xml_value(root, document)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8") + "\n"


def serialize_document(document: Any, output_format: str, xml_root_name: str = "result") -> str:
    if output_format == "yaml":
        return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    if output_format == "json":
        return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if output_format == "xml":
        return serialize_xml(document, xml_root_name)
    raise CliArgumentError(f"Unsupported output format '{output_format}'.")


def extension_for_format(output_format: str) -> str:
    try:
        return {"yaml": "yml", "json": "json", "xml": "xml"}[output_format]
    except KeyError as exc:
        raise CliArgumentError(f"Unsupported output format '{output_format}'.") from exc


def _atomic_write_text(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            handle.write(text)
            temp_name = handle.name
        os.replace(temp_name, path)
    except OSError as exc:
        raise OutputWriteError(f"Cannot write output file '{path}': {exc}") from exc


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
            handle.write(data)
            temp_name = handle.name
        os.replace(temp_name, path)
    except OSError as exc:
        raise OutputWriteError(f"Cannot write output file '{path}': {exc}") from exc


def write_result(document: Any, output_format: str, output_path: Path | None, xml_root_name: str = "result") -> None:
    text = serialize_document(document, output_format, xml_root_name)
    if output_path is None:
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except OSError as exc:
            raise OutputWriteError(f"Cannot write result to stdout: {exc}") from exc
    else:
        _atomic_write_text(output_path, text)


def write_binary_result(data: bytes, output_path: Path | None) -> None:
    if output_path is None:
        try:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        except OSError as exc:
            raise OutputWriteError(f"Cannot write binary result to stdout: {exc}") from exc
    else:
        _atomic_write_bytes(output_path, data)
