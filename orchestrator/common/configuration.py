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
    package_path: Path


class ConfigurationRepository:
    """Discovers configuration entity packages and loads their YAML definitions lazily."""

    def __init__(self, config_root: Path, categories: Iterable[ConfigurationCategory], schema_validator):
        self.config_root = config_root.expanduser().resolve()
        self.categories = {category.name: category for category in categories}
        self.schema_validator = schema_validator
        self._entries: dict[str, dict[str, ConfigurationEntry]] = {}
        self._by_id: dict[str, dict[str, list[ConfigurationEntry]]] = {}
        self._invalid_layout_files: list[Path] = []
        self.loaded_entries: dict[tuple[str, str], ConfigurationEntry] = {}
        self._accessed_entries: dict[tuple[str, str], ConfigurationEntry] = {}
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
                self._discover_category(root, resolved_root, category, entries, by_id)
            self._entries[category.name] = entries
            self._by_id[category.name] = by_id

    def _discover_category(
        self,
        root: Path,
        resolved_root: Path,
        category: ConfigurationCategory,
        entries: dict[str, ConfigurationEntry],
        by_id: dict[str, list[ConfigurationEntry]],
    ) -> None:
        visited: set[Path] = set()

        def visit(directory: Path) -> None:
            resolved_directory = directory.resolve()
            try:
                resolved_directory.relative_to(resolved_root)
            except ValueError as exc:
                raise ConfigurationValidationError(
                    f"Configuration directory '{directory}' escapes category root '{root}' through a symlink."
                ) from exc
            if resolved_directory in visited:
                raise ConfigurationValidationError(
                    f"Configuration directory graph contains a symlink cycle or duplicate directory reference at '{directory}'."
                )
            visited.add(resolved_directory)

            # Category root itself is a namespace. Every entity below it is represented
            # by <entity-id>/<entity-id>.yml. Once such a directory is found, its whole
            # subtree is payload/attachments and is not scanned for further entities.
            if directory != root:
                entity_id = directory.name
                definition = directory / f"{entity_id}.yml"
                yaml_spelling = directory / f"{entity_id}.yaml"
                if definition.is_file():
                    resolved_definition = definition.resolve()
                    try:
                        resolved_definition.relative_to(resolved_root)
                    except ValueError as exc:
                        raise ConfigurationValidationError(
                            f"Configuration file '{definition}' escapes category root '{root}' through a symlink."
                        ) from exc
                    relative_package = directory.relative_to(root)
                    reference = relative_package.as_posix()
                    entry = ConfigurationEntry(category.name, reference, definition, directory)
                    if reference in entries:
                        raise ConfigurationValidationError(
                            f"Duplicate {category.name} configuration reference '{reference}'."
                        )
                    entries[reference] = entry
                    by_id.setdefault(entity_id, []).append(entry)
                    return
                if yaml_spelling.exists():
                    self._invalid_layout_files.append(yaml_spelling)

            try:
                children = sorted(directory.iterdir(), key=lambda p: p.name)
            except OSError as exc:
                raise ConfigurationValidationError(
                    f"Cannot scan configuration directory '{directory}': {exc}"
                ) from exc

            for child in children:
                if child.is_dir():
                    visit(child)
                elif child.is_file() and child.suffix.lower() in (".yml", ".yaml"):
                    # YAML files outside an entity package are not configuration
                    # entities in the package-based layout.
                    self._invalid_layout_files.append(child)

        visit(root)

    def validate_file_extensions(self) -> None:
        if self._invalid_layout_files:
            formatted = "\n".join(f"  - {p}" for p in sorted(set(self._invalid_layout_files)))
            raise ConfigurationValidationError(
                "Every configuration entity must be stored as '<id>/<id>.yml' inside its category tree; "
                "'.yaml' configuration definitions and loose YAML configuration files are not supported. Found:\n"
                + formatted
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
        self._accessed_entries[key] = entry
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
        expected_id = entry.package_path.name
        if entry.path.stem != expected_id or value != expected_id:
            raise ConfigurationValidationError(
                f"Configuration package invariant failed for '{entry.path}': directory name, YAML file base name "
                f"and entity id must all be '{expected_id}', actual entity id is '{value}'."
            )

        self.schema_validator.validate(document, category.schema_name, entry.path)
        self._cache[key] = document
        self.loaded_entries[key] = entry
        return document

    def resolve(self, category: str, reference: str) -> tuple[ConfigurationEntry, dict[str, Any]]:
        entry = self.resolve_entry(category, reference)
        return entry, self.load_entry(entry)

    def clear_access_log(self) -> None:
        self._accessed_entries = {}

    def accessed_entries(self) -> list[ConfigurationEntry]:
        return list(self._accessed_entries.values())

    @staticmethod
    def resolve_package_relative_path(entry: ConfigurationEntry, relative_path: str, require_exists: bool = True) -> Path:
        if not relative_path or "\\" in relative_path:
            raise ConfigurationValidationError(
                f"Invalid package-relative path '{relative_path}' in configuration '{entry.reference}'."
            )
        logical = PurePosixPath(relative_path)
        if logical.is_absolute() or any(part in ("", ".", "..") for part in logical.parts):
            raise ConfigurationValidationError(
                f"Package-relative path '{relative_path}' in configuration '{entry.reference}' must not be absolute "
                "or contain '.'/'..'."
            )
        path = entry.package_path.joinpath(*logical.parts)
        resolved_package = entry.package_path.resolve()
        resolved = path.resolve()
        try:
            resolved.relative_to(resolved_package)
        except ValueError as exc:
            raise ConfigurationValidationError(
                f"Package-relative path '{relative_path}' in configuration '{entry.reference}' escapes its entity package."
            ) from exc
        if require_exists and not path.exists():
            raise ConfigurationValidationError(
                f"Package-relative path '{relative_path}' referenced by configuration '{entry.reference}' does not exist "
                f"inside '{entry.package_path}'."
            )
        return path
