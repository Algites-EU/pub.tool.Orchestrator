from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource

from orchestrator.common.errors import ConfigurationValidationError


class SchemaValidator:
    def __init__(self, model_directory: Path):
        self.model_directory = model_directory.resolve()
        self.schemas: dict[str, dict[str, Any]] = {}
        for path in sorted(self.model_directory.glob("*.schema.yml")):
            with path.open("r", encoding="utf-8") as handle:
                schema = yaml.safe_load(handle)
            self.schemas[path.name] = schema
        resources = []
        for schema in self.schemas.values():
            schema_id = schema.get("$id")
            if schema_id:
                resources.append((schema_id, Resource.from_contents(schema)))
        self.registry = Registry().with_resources(resources)

    def check_schemas(self) -> None:
        for name, schema in self.schemas.items():
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as exc:
                raise ConfigurationValidationError(
                    f"Schema '{name}' is invalid: {exc.message}"
                ) from exc

    def validate(self, document: Any, schema_name: str, source: Path | str) -> None:
        try:
            schema = self.schemas[schema_name]
        except KeyError as exc:
            raise ConfigurationValidationError(f"Unknown schema '{schema_name}'.") from exc
        validator = Draft202012Validator(schema, registry=self.registry)
        errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
        if errors:
            rendered = []
            for error in errors:
                location = ".".join(str(part) for part in error.absolute_path) or "<root>"
                rendered.append(f"  - {location}: {error.message}")
            raise ConfigurationValidationError(
                f"Schema validation failed for '{source}' against '{schema_name}':\n" + "\n".join(rendered)
            )
