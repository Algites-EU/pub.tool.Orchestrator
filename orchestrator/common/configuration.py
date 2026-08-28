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


OPERATING_SYSTEM_IMPLEMENTATION_DIRECTORIES = {
    "NIXOS": "nixos",
    "DEBIAN": "debian",
    "LINUX": "linux",
    "WINDOWS": "windows",
    "MACOS": "macos",
}


def operating_system_implementation_directory(os_type: str) -> str:
    try:
        return OPERATING_SYSTEM_IMPLEMENTATION_DIRECTORIES[os_type]
    except KeyError as exc:
        raise ConfigurationValidationError(
            f"Unsupported operating system type '{os_type}' for implementation directory selection."
        ) from exc


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
    config_version: str
    path: Path
    package_path: Path
    entity_package_path: Path


class ConfigurationRepository:
    """Discovers versioned configuration entity packages and loads YAML definitions lazily."""

    def __init__(self, config_root: Path, categories: Iterable[ConfigurationCategory], schema_validator):
        self.config_root = config_root.expanduser().resolve()
        self.categories = {category.name: category for category in categories}
        self.schema_validator = schema_validator
        self._entries: dict[str, dict[str, dict[str, ConfigurationEntry]]] = {}
        self._by_id: dict[str, dict[str, list[ConfigurationEntry]]] = {}
        self._invalid_layout_files: list[Path] = []
        self.loaded_entries: dict[tuple[str, str, str], ConfigurationEntry] = {}
        self._accessed_entries: dict[tuple[str, str, str], ConfigurationEntry] = {}
        self._cache: dict[tuple[str, str, str], dict[str, Any]] = {}
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

    @staticmethod
    def validate_config_version(config_version: str) -> str:
        if not isinstance(config_version, str) or not config_version:
            raise UnresolvedReferenceError("Configuration reference must contain a non-empty string config version.")
        if any(ch in config_version for ch in ("/", "\\")) or config_version in (".", ".."):
            raise UnresolvedReferenceError(f"Invalid configuration version '{config_version}'.")
        return config_version

    @classmethod
    def split_reference(cls, value: Any) -> tuple[str, str]:
        if not isinstance(value, dict):
            raise UnresolvedReferenceError(
                "Configuration references must be objects containing 'reference' and 'reference_config_version'."
            )
        try:
            reference = value["reference"]
            config_version = value["reference_config_version"]
        except KeyError as exc:
            raise UnresolvedReferenceError(
                "Configuration reference must contain both 'reference' and 'reference_config_version'."
            ) from exc
        if not isinstance(reference, str):
            raise UnresolvedReferenceError("Configuration reference field 'reference' must be a string.")
        return cls.validate_reference(reference), cls.validate_config_version(config_version)

    @classmethod
    def make_reference(cls, entry: ConfigurationEntry) -> dict[str, str]:
        return {"reference": entry.reference, "reference_config_version": entry.config_version}

    def _discover(self) -> None:
        if not self.config_root.is_dir():
            raise ConfigurationValidationError(
                f"Configuration root '{self.config_root}' does not exist or is not a directory."
            )

        for category in self.categories.values():
            logical_folder = self._validate_folder_name(category.folder_name)
            root = self.config_root.joinpath(*logical_folder.parts)
            entries: dict[str, dict[str, ConfigurationEntry]] = {}
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
        entries: dict[str, dict[str, ConfigurationEntry]],
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

            # Category root and namespace directories are traversed recursively. An entity
            # directory is recognized by one or more version subdirectories containing
            # <entity-id>_<config-version>.yml. Once recognized, its version directories
            # are configuration packages and their subtrees are attachments, not namespaces.
            if directory != root:
                entity_id = directory.name
                version_entries: list[ConfigurationEntry] = []
                try:
                    children = sorted(directory.iterdir(), key=lambda p: p.name)
                except OSError as exc:
                    raise ConfigurationValidationError(
                        f"Cannot scan configuration directory '{directory}': {exc}"
                    ) from exc
                for child in children:
                    if not child.is_dir():
                        continue
                    version = child.name
                    definition = child / f"{entity_id}_{version}.yml"
                    yaml_spelling = child / f"{entity_id}_{version}.yaml"
                    if definition.is_file():
                        resolved_definition = definition.resolve()
                        try:
                            resolved_definition.relative_to(resolved_root)
                        except ValueError as exc:
                            raise ConfigurationValidationError(
                                f"Configuration file '{definition}' escapes category root '{root}' through a symlink."
                            ) from exc
                        relative_entity = directory.relative_to(root)
                        reference = relative_entity.as_posix()
                        version_entries.append(
                            ConfigurationEntry(category.name, reference, version, definition, child, directory)
                        )
                    elif yaml_spelling.exists():
                        self._invalid_layout_files.append(yaml_spelling)

                if version_entries:
                    reference = version_entries[0].reference
                    versions = entries.setdefault(reference, {})
                    for entry in version_entries:
                        if entry.config_version in versions:
                            raise ConfigurationValidationError(
                                f"Duplicate {category.name} configuration '{reference}' version '{entry.config_version}'."
                            )
                        versions[entry.config_version] = entry
                        by_id.setdefault(entity_id, []).append(entry)
                    # Old unversioned entity definition or loose YAML at entity root is invalid.
                    for child in children:
                        if child.is_file() and child.suffix.lower() in (".yml", ".yaml"):
                            self._invalid_layout_files.append(child)
                    return

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
                    self._invalid_layout_files.append(child)

        visit(root)

    def validate_file_extensions(self) -> None:
        if self._invalid_layout_files:
            formatted = "\n".join(f"  - {p}" for p in sorted(set(self._invalid_layout_files)))
            raise ConfigurationValidationError(
                "Every configuration entity must be stored as '<id>/<config-version>/<id>_<config-version>.yml' "
                "inside its category tree; '.yaml' configuration definitions and loose YAML configuration files "
                "are not supported. Found:\n" + formatted
            )

    def all_entries(self, category: str | None = None) -> list[ConfigurationEntry]:
        names = [category] if category is not None else list(self.categories)
        result: list[ConfigurationEntry] = []
        for name in names:
            for versions in self._entries[name].values():
                result.extend(versions.values())
        return result

    def resolve_entry(self, category: str, reference: str, config_version: str) -> ConfigurationEntry:
        reference = self.validate_reference(reference)
        config_version = self.validate_config_version(config_version)
        if "/" in reference:
            entry = self._entries[category].get(reference, {}).get(config_version)
            if entry is None:
                known = self._entries[category].get(reference, {})
                if known:
                    available = ", ".join(sorted(known))
                    raise UnresolvedReferenceError(
                        f"Referenced {category} configuration '{reference}' does not have config version "
                        f"'{config_version}'. Available versions: {available}."
                    )
                raise UnresolvedReferenceError(
                    f"Referenced {category} configuration '{reference}' does not exist."
                )
            return entry

        candidates = [
            entry for entry in self._by_id[category].get(reference, [])
            if entry.config_version == config_version
        ]
        if not candidates:
            all_candidates = self._by_id[category].get(reference, [])
            if all_candidates:
                available = ", ".join(sorted({entry.config_version for entry in all_candidates}))
                raise UnresolvedReferenceError(
                    f"Referenced {category} configuration '{reference}' does not have config version "
                    f"'{config_version}'. Available versions: {available}."
                )
            raise UnresolvedReferenceError(
                f"Referenced {category} configuration '{reference}' does not exist."
            )
        if len(candidates) > 1:
            rendered = "\n".join(
                f"  - {candidate.reference}@{candidate.config_version}" for candidate in candidates
            )
            raise AmbiguousReferenceError(
                f"Ambiguous {category} configuration reference '{reference}' version '{config_version}'. Candidates:\n{rendered}"
            )
        return candidates[0]

    def load_entry(self, entry: ConfigurationEntry) -> dict[str, Any]:
        key = (entry.category, entry.reference, entry.config_version)
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
                f"Configuration '{entry.path}' does not contain entity id at {'.'.join(category.entity_path)}."
            ) from exc
        expected_id = entry.entity_package_path.name
        entity_object = document
        for key_part in category.entity_path[:-1]:
            entity_object = entity_object[key_part]
        actual_version = entity_object.get("config_version") if isinstance(entity_object, dict) else None
        if entry.path.stem != f"{expected_id}_{entry.config_version}" or value != expected_id or actual_version != entry.config_version:
            raise ConfigurationValidationError(
                f"Configuration package invariant failed for '{entry.path}': entity directory/id must be '{expected_id}', "
                f"version directory and entity config_version must be '{entry.config_version}', and YAML file must be "
                f"'{expected_id}_{entry.config_version}.yml'. Actual entity id is '{value}', config_version is '{actual_version}'."
            )

        self.schema_validator.validate(document, category.schema_name, entry.path)
        if entry.category == "services":
            self._validate_service_package_layout(entry)
        self._cache[key] = document
        self.loaded_entries[key] = entry
        return document

    @staticmethod
    def _validate_service_package_layout(entry: ConfigurationEntry) -> None:
        branches = ("common", "consumer", "provider")
        missing = [name for name in branches if not (entry.package_path / name).is_dir()]
        if missing:
            raise ConfigurationValidationError(
                f"Service configuration package '{entry.reference}@{entry.config_version}' must contain the fixed "
                f"definition directories common/, consumer/ and provider/. Missing: {', '.join(missing)}."
            )

        allowed_directories = set(OPERATING_SYSTEM_IMPLEMENTATION_DIRECTORIES.values())
        for branch_name in branches:
            branch = entry.package_path / branch_name
            for child in branch.iterdir():
                if child.is_file():
                    raise ConfigurationValidationError(
                        f"Service configuration package '{entry.reference}@{entry.config_version}' must place "
                        f"{branch_name} implementation files below an operating-system subdirectory such as "
                        f"{branch_name}/nixos/ or {branch_name}/debian/. Direct file is not allowed: '{child.name}'."
                    )
                if child.is_dir() and child.name not in allowed_directories:
                    allowed = ", ".join(sorted(allowed_directories))
                    raise ConfigurationValidationError(
                        f"Service configuration package '{entry.reference}@{entry.config_version}' contains unsupported "
                        f"operating-system implementation directory '{branch_name}/{child.name}/'. Allowed directory "
                        f"names are: {allowed}."
                    )

    def resolve(self, category: str, reference: Any, config_version: str | None = None) -> tuple[ConfigurationEntry, dict[str, Any]]:
        if config_version is None:
            reference, config_version = self.split_reference(reference)
        entry = self.resolve_entry(category, reference, config_version)
        return entry, self.load_entry(entry)

    def clear_access_log(self) -> None:
        self._accessed_entries = {}

    def accessed_entries(self) -> list[ConfigurationEntry]:
        return list(self._accessed_entries.values())

    @staticmethod
    def resolve_package_relative_path(entry: ConfigurationEntry, relative_path: str, require_exists: bool = True) -> Path:
        if not relative_path or "\\" in relative_path:
            raise ConfigurationValidationError(
                f"Invalid package-relative path '{relative_path}' in '{entry.reference}@{entry.config_version}'."
            )
        logical = PurePosixPath(relative_path)
        if logical.is_absolute() or any(part in ("", ".", "..") for part in logical.parts):
            raise ConfigurationValidationError(
                f"Package-relative path '{relative_path}' in '{entry.reference}@{entry.config_version}' must be relative and must not contain '.' or '..'."
            )
        candidate = entry.package_path.joinpath(*logical.parts)
        resolved_package = entry.package_path.resolve()
        resolved_candidate = candidate.resolve()
        try:
            resolved_candidate.relative_to(resolved_package)
        except ValueError as exc:
            raise ConfigurationValidationError(
                f"Package-relative path '{relative_path}' in '{entry.reference}@{entry.config_version}' escapes the configuration package."
            ) from exc
        if require_exists and not candidate.exists():
            raise ConfigurationValidationError(
                f"Package-relative path '{relative_path}' in '{entry.reference}@{entry.config_version}' does not exist."
            )
        return candidate
