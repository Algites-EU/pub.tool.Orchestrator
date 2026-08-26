from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import yaml

from .errors import (
    AmbiguousReferenceError,
    ConfigurationValidationError,
    UnresolvedReferenceError,
)


@dataclass(frozen=True)
class ConfigurationCategory:
    name: str
    folder_name: str
    schema_name: str
    entity_path: tuple[str, ...]


@dataclass(frozen=True)
class ConfigurationEntry:
    category: str
    reference: str
    path: Path


class ConfigurationRepository:
    """Discovers configuration files by path and loads them lazily."""

    def __init__(self, config_root: Path, categories: Iterable[ConfigurationCategory], schema_validator):
        self.config_root = config_root.expanduser().resolve()
        self.categories = {category.name: category for category in categories}
        self.schema_validator = schema_validator
        self._entries: dict[str, dict[str, ConfigurationEntry]] = {}
        self._by_id: dict[str, dict[str, list[ConfigurationEntry]]] = {}
        self._unsupported_yaml: list[Path] = []
        self.loaded_entries: dict[tuple[str, str], ConfigurationEntry] = {}
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._discover()

    @staticmethod
    def _validate_folder_name(folder_name: str) -> PurePosixPath:
        if "\\" in folder_name:
            raise ConfigurationValidationError(
                f"Configuration folder name '{folder_name}' must use '/' separators."
            )
        logical = PurePosixPath(folder_name)
        if logical.is_absolute() or not logical.parts or any(part in ("", ".", "..") for part in logical.parts):
            raise ConfigurationValidationError(
                f"Configuration folder name '{folder_name}' must be a relative path without '.' or '..'."
            )
        return logical

    @staticmethod
    def validate_reference(reference: str) -> str:
        if not reference or "\\" in reference:
            raise UnresolvedReferenceError(
                f"Invalid configuration reference '{reference}'. References use relative '/'-separated paths."
            )
        logical = PurePosixPath(reference)
        if logical.is_absolute() or any(part in ("", ".", "..") for part in logical.parts):
            raise UnresolvedReferenceError(
                f"Invalid configuration reference '{reference}'. Absolute paths, '.' and '..' are not allowed."
            )
        return logical.as_posix()

    def _discover(self) -> None:
        if not self.config_root.is_dir():
            raise ConfigurationValidationError(
                f"Configuration root '{self.config_root}' does not exist or is not a directory."
            )

        for category in self.categories.values():
            logical_folder = self._validate_folder_name(category.folder_name)
            root = self.config_root.joinpath(*logical_folder.parts)
            entries: dict[str, ConfigurationEntry] = {}
            by_id: dict[str, list[ConfigurationEntry]] = {}
            if root.exists():
                resolved_root = root.resolve()
                try:
                    resolved_root.relative_to(self.config_root)
                except ValueError as exc:
                    raise ConfigurationValidationError(
                        f"Configuration folder '{root}' escapes configuration root '{self.config_root}'."
                    ) from exc
                if not root.is_dir():
                    raise ConfigurationValidationError(
                        f"Configuration folder '{root}' is not a directory."
                    )
                for path in sorted(root.rglob("*")):
                    if not path.is_file():
                        continue
                    if path.suffix == ".yaml":
                        self._unsupported_yaml.append(path)
                        continue
                    if path.suffix != ".yml":
                        continue
                    resolved = path.resolve()
                    try:
                        relative = resolved.relative_to(resolved_root)
                    except ValueError as exc:
                        raise ConfigurationValidationError(
                            f"Configuration file '{path}' escapes category root '{root}' through a symlink."
                        ) from exc
                    reference = relative.with_suffix("").as_posix()
                    entry = ConfigurationEntry(category.name, reference, path)
                    entries[reference] = entry
                    entity_id = relative.stem
                    by_id.setdefault(entity_id, []).append(entry)
            self._entries[category.name] = entries
            self._by_id[category.name] = by_id

    def validate_file_extensions(self) -> None:
        if self._unsupported_yaml:
            formatted = "\n".join(f"  - {p}" for p in self._unsupported_yaml)
            raise ConfigurationValidationError(
                "Only the '.yml' extension is supported for configuration files. Found:\n" + formatted
            )

    def all_entries(self, category: str | None = None) -> list[ConfigurationEntry]:
        if category is not None:
            return list(self._entries[category].values())
        result: list[ConfigurationEntry] = []
        for name in self.categories:
            result.extend(self._entries[name].values())
        return result

    def resolve_entry(self, category: str, reference: str) -> ConfigurationEntry:
        reference = self.validate_reference(reference)
        if "/" in reference:
            entry = self._entries[category].get(reference)
            if entry is None:
                raise UnresolvedReferenceError(
                    f"Referenced {category} configuration '{reference}' does not exist."
                )
            return entry

        candidates = self._by_id[category].get(reference, [])
        if not candidates:
            raise UnresolvedReferenceError(
                f"Referenced {category} configuration '{reference}' does not exist."
            )
        if len(candidates) > 1:
            rendered = "\n".join(f"  - {candidate.reference}" for candidate in candidates)
            raise AmbiguousReferenceError(
                f"Ambiguous {category} configuration reference '{reference}'. Candidates:\n{rendered}"
            )
        return candidates[0]

    def load_entry(self, entry: ConfigurationEntry) -> dict[str, Any]:
        key = (entry.category, entry.reference)
        if key in self._cache:
            return self._cache[key]
        try:
            with entry.path.open("r", encoding="utf-8") as handle:
                document = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigurationValidationError(
                f"Cannot read YAML configuration '{entry.path}': {exc}"
            ) from exc
        if not isinstance(document, dict):
            raise ConfigurationValidationError(
                f"Configuration '{entry.path}' must contain one YAML object at the document root."
            )

        category = self.categories[entry.category]
        value: Any = document
        try:
            for key_part in category.entity_path:
                value = value[key_part]
        except (KeyError, TypeError) as exc:
            raise ConfigurationValidationError(
                f"Configuration '{entry.path}' does not contain entity id at "
                f"{'.'.join(category.entity_path)}."
            ) from exc
        if value != entry.path.stem:
            raise ConfigurationValidationError(
                f"Configuration ID does not match file name for '{entry.path}': "
                f"expected '{entry.path.stem}', actual '{value}'."
            )

        self.schema_validator.validate(document, category.schema_name, entry.path)
        self._cache[key] = document
        self.loaded_entries[key] = entry
        return document

    def resolve(self, category: str, reference: str) -> tuple[ConfigurationEntry, dict[str, Any]]:
        entry = self.resolve_entry(category, reference)
        return entry, self.load_entry(entry)
