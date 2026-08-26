from __future__ import annotations

from typing import Any

from orchestrator.common.configuration import ConfigurationRepository
from orchestrator.common.errors import ConfigurationValidationError, ResolutionError
from orchestrator.deployment.resolver.deployment import DeploymentResolver


class DeploymentConfigurationValidator:
    def __init__(self, repository: ConfigurationRepository, resolver: DeploymentResolver):
        self.repository = repository
        self.resolver = resolver

    def validate_all(self) -> dict[str, Any]:
        self.repository.validate_file_extensions()
        entries = self.repository.all_entries()
        for entry in entries:
            self.repository.load_entry(entry)

        # Cross-file validation for every independent configuration.
        for entry in self.repository.all_entries("environments"):
            environment = self.repository.load_entry(entry)
            self.resolver._validate_environment(environment)
        for entry in self.repository.all_entries("hosts"):
            host = self.repository.load_entry(entry)
            environment_entry, environment = self.repository.resolve("environments", host["environment"])
            self.resolver._validate_environment(environment)
            self.resolver._validate_host(entry, host, environment_entry, environment)
        for entry in self.repository.all_entries("guests"):
            self.resolver._validate_guest(self.repository.load_entry(entry), entry)
        for entry in self.repository.all_entries("shared_mountable_resources"):
            shared = self.repository.load_entry(entry)
            host_entry, host = self.repository.resolve("hosts", shared["host"])
            environment_entry, environment = self.repository.resolve("environments", host["environment"])
            self.resolver._validate_environment(environment)
            self.resolver._validate_host(host_entry, host, environment_entry, environment)
            target = self.resolver._compatible_target(
                host, shared["host_storage_target"], shared["storage_class"], shared["representation"]
            )
            self.resolver._select_backend(target, shared["representation"], shared.get("backend"))
            if shared["representation"] == "FILESYSTEM" and shared.get("host_mountable_resource_interface"):
                provider = shared["host_mountable_resource_interface"]
                if provider not in host["mountable_resource_interfaces"]:
                    raise ConfigurationValidationError(
                        f"Shared resource '{entry.reference}' references unknown filesystem provider '{provider}'."
                    )
        for entry in self.repository.all_entries("deployments"):
            self.resolver.resolve(entry.reference)

        return {
            "valid": True,
            "scope": "all",
            "validated_files": [
                f"{entry.category}:{entry.reference}" for entry in sorted(entries, key=lambda item: (item.category, item.reference))
            ],
        }

    def validate_deployment(self, deployment_reference: str) -> dict[str, Any]:
        plan = self.resolver.resolve(deployment_reference)
        entries = sorted(self.repository.loaded_entries.values(), key=lambda item: (item.category, item.reference))
        return {
            "valid": True,
            "scope": "deployment",
            "deployment": plan["deployment"],
            "validated_files": [f"{entry.category}:{entry.reference}" for entry in entries],
        }
