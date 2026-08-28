from __future__ import annotations

import io
import logging
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator
from zipfile import ZIP_DEFLATED, ZipFile

from orchestrator.common.configuration import ConfigurationEntry, ConfigurationRepository
from orchestrator.common.errors import ConfigurationValidationError
from orchestrator.common.io import extension_for_format, serialize_document
from orchestrator.deployment.resolver import DeploymentResolver


_BUNDLE_CATEGORY_FOLDERS = {
    "deployments": "guest-deployment",
    "environments": "environment",
    "guests": "guest",
    "hosts": "host",
    "shared_mountable_resources": "shared-mountable-resource",
    "services": "service",
}


class DeploymentBundleBuilder:
    """Builds a portable ZIP containing one or more plans and their configuration packages."""

    def __init__(
        self,
        repository: ConfigurationRepository,
        resolver: DeploymentResolver,
        schema_validator,
        logger: logging.Logger | None = None,
    ):
        self.repository = repository
        self.resolver = resolver
        self.schema_validator = schema_validator
        self.logger = logger or logging.getLogger("algites_orchestrator")

    def build(
        self, deployment_references: Iterable[tuple[str, str]], plan_format: str,
        allowed_config_version_states: set[str] | None = None,
    ) -> bytes:
        references = list(deployment_references)
        if not references:
            raise ConfigurationValidationError("A DeploymentBundle must contain at least one deployment.")

        extension = extension_for_format(plan_format)
        buffer = io.BytesIO()
        manifest_deployments: list[dict[str, Any]] = []

        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            for requested_reference, requested_version in references:
                self.logger.info(
                    "Resolving deployment '%s@%s' for bundle.", requested_reference, requested_version
                )
                plan = self.resolver.resolve(
                    requested_reference, requested_version, allowed_config_version_states
                )
                dependency_entries = sorted(
                    self.repository.accessed_entries(),
                    key=lambda entry: (entry.category, entry.reference, entry.config_version),
                )

                deployment_reference = plan["deployment"]["reference"]
                deployment_version = plan["deployment"]["reference_config_version"]
                deployment_id = PurePosixPath(deployment_reference).name
                deployment_root = (
                    PurePosixPath("deployment-bundle") / "deployments" / deployment_reference / deployment_version
                )
                plan_relative = (
                    PurePosixPath("deployments") / deployment_reference / deployment_version
                    / f"{deployment_id}_{deployment_version}_deployment-plan.{extension}"
                )
                plan_archive_path = PurePosixPath("deployment-bundle") / plan_relative
                plan_text = serialize_document(plan, plan_format, "deployment-plan")
                archive.writestr(plan_archive_path.as_posix(), plan_text.encode("utf-8"))

                attachment_records: list[dict[str, str]] = []
                for entry in dependency_entries:
                    bundle_category = _BUNDLE_CATEGORY_FOLDERS.get(entry.category, entry.category.replace("_", "-"))
                    package_relative = PurePosixPath(bundle_category) / entry.reference / entry.config_version
                    package_archive_root = deployment_root / package_relative
                    self._copy_package(archive, entry, package_archive_root)
                    attachment_records.append(
                        {
                            "category": entry.category,
                            "reference": entry.reference,
                            "reference_config_version": entry.config_version,
                            "path": (
                                PurePosixPath("deployments") / deployment_reference / deployment_version / package_relative
                            ).as_posix(),
                        }
                    )

                manifest_deployments.append(
                    {
                        "id": deployment_id,
                        "reference": deployment_reference,
                        "reference_config_version": deployment_version,
                        "deployment_plan": plan_relative.as_posix(),
                        "attachments": attachment_records,
                    }
                )

            manifest = {
                "bundle_version": 1,
                "model_version": 1,
                "deployment_plan_format": plan_format,
                "deployments": manifest_deployments,
            }
            self.schema_validator.validate(
                manifest, "deployment-bundle-manifest.schema.yml", "generated DeploymentBundle manifest"
            )
            manifest_text = serialize_document(manifest, plan_format, "deployment-bundle-manifest")
            archive.writestr(
                f"deployment-bundle/manifest.{extension}", manifest_text.encode("utf-8")
            )

        return buffer.getvalue()

    def _copy_package(self, archive: ZipFile, entry: ConfigurationEntry, archive_root: PurePosixPath) -> None:
        for source, relative in self._iter_package_files(entry):
            archive.write(source, (archive_root / PurePosixPath(relative.as_posix())).as_posix())

    def _iter_package_files(self, entry: ConfigurationEntry) -> Iterator[tuple[Path, Path]]:
        package = entry.package_path
        resolved_package = package.resolve()

        def visit(directory: Path, relative_directory: Path, active: set[Path]):
            resolved_directory = directory.resolve()
            try:
                resolved_directory.relative_to(resolved_package)
            except ValueError as exc:
                raise ConfigurationValidationError(
                    f"Configuration package '{entry.reference}' contains directory '{directory}' escaping the package."
                ) from exc
            if resolved_directory in active:
                raise ConfigurationValidationError(
                    f"Configuration package '{entry.reference}' contains a directory symlink cycle at '{directory}'."
                )
            next_active = set(active)
            next_active.add(resolved_directory)
            try:
                children = sorted(directory.iterdir(), key=lambda path: path.name)
            except OSError as exc:
                raise ConfigurationValidationError(
                    f"Cannot read configuration package directory '{directory}': {exc}"
                ) from exc
            for child in children:
                relative = relative_directory / child.name
                resolved_child = child.resolve()
                try:
                    resolved_child.relative_to(resolved_package)
                except ValueError as exc:
                    raise ConfigurationValidationError(
                        f"Configuration package '{entry.reference}' contains '{child}' escaping the package through a symlink."
                    ) from exc
                if child.is_dir():
                    yield from visit(child, relative, next_active)
                elif child.is_file():
                    yield child, relative

        yield from visit(package, Path(), set())
