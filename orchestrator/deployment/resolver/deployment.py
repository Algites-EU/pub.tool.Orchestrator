from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from orchestrator.common.configuration import ConfigurationEntry, ConfigurationRepository
from orchestrator.common.errors import ConfigurationValidationError, ResolutionError
from .sizes import size_to_bytes


@dataclass
class PlacementFacts:
    resource_id: str
    host_reference: str
    host: dict[str, Any]
    environment_reference: str
    environment: dict[str, Any]
    target_id: str
    target: dict[str, Any]
    storage_identity: str
    dependency_hosts: set[str] | None
    dependency_sites: set[str] | None


class DeploymentResolver:
    def __init__(self, repository: ConfigurationRepository, plan_schema_validator, logger: logging.Logger | None = None):
        self.repository = repository
        self.plan_schema_validator = plan_schema_validator
        self.logger = logger or logging.getLogger("algites_orchestrator")

    def resolve(self, deployment_reference: str) -> dict[str, Any]:
        deployment_entry, deployment = self.repository.resolve("deployments", deployment_reference)
        guest_entry, guest = self.repository.resolve("guests", deployment["guest"])
        host_entry, host = self.repository.resolve("hosts", deployment["host"])
        environment_entry, environment = self.repository.resolve("environments", host["environment"])

        self._validate_environment(environment)
        self._validate_host(host_entry, host, environment_entry, environment)
        self._validate_guest(guest)
        self._validate_compute(deployment, guest)
        resolved_networks = self._resolve_networks(deployment, guest, host)
        resolved_resources, facts = self._resolve_resources(
            deployment_entry, deployment, guest, host_entry, host, environment_entry, environment
        )
        relation_results, warnings = self._resolve_relations(guest, facts)

        plan = {
            "model_version": 1,
            "deployment": deployment_entry.reference,
            "guest": guest_entry.reference,
            "host": host_entry.reference,
            "resolved_compute": self._resolve_compute(deployment, guest),
            "resolved_network_interfaces": resolved_networks,
            "resolved_mountable_resources": resolved_resources,
            "relation_results": relation_results,
            "warnings": warnings,
        }
        self.plan_schema_validator.validate(plan, "deployment-plan.schema.yml", "generated DeploymentPlan")
        return plan

    def _validate_environment(self, environment: dict[str, Any]) -> None:
        sites = environment["sites"]
        hosts = environment["hosts"]
        for host_id, host in hosts.items():
            if host["site"] not in sites:
                raise ConfigurationValidationError(
                    f"Environment host '{host_id}' references unknown site '{host['site']}'."
                )
        for storage_id, storage in environment["storage_systems"].items():
            for host_id in storage.get("impacted_hosts", []):
                if host_id not in hosts:
                    raise ConfigurationValidationError(
                        f"Storage system '{storage_id}' references unknown impacted host '{host_id}'."
                    )
            for site_id in storage.get("impacted_sites", []):
                if site_id not in sites:
                    raise ConfigurationValidationError(
                        f"Storage system '{storage_id}' references unknown impacted site '{site_id}'."
                    )

    def _validate_host(
        self,
        host_entry: ConfigurationEntry,
        host: dict[str, Any],
        environment_entry: ConfigurationEntry,
        environment: dict[str, Any],
    ) -> None:
        host_id = host["host"]["id"]
        if host_id not in environment["hosts"]:
            raise ConfigurationValidationError(
                f"Host '{host_entry.reference}' is not registered as '{host_id}' in environment "
                f"'{environment_entry.reference}'."
            )
        for target_id, target in host["storage_targets"].items():
            storage_system = target["storage_system"]
            if storage_system != "HOST_LOCAL_STORAGE" and storage_system not in environment["storage_systems"]:
                raise ConfigurationValidationError(
                    f"Host storage target '{target_id}' references unknown storage system '{storage_system}'."
                )
            for device in target.get("impacted_devices", []):
                if device not in host["storage_devices"]:
                    raise ConfigurationValidationError(
                        f"Host storage target '{target_id}' references unknown impacted device '{device}'."
                    )
            for controller in target.get("impacted_controllers", []):
                if controller not in host["storage_controllers"]:
                    raise ConfigurationValidationError(
                        f"Host storage target '{target_id}' references unknown impacted controller '{controller}'."
                    )
        for provider_id, provider in host["mountable_resource_interfaces"].items():
            network = provider.get("host_network")
            if network is not None and network not in host["networks"]:
                raise ConfigurationValidationError(
                    f"Mountable resource interface '{provider_id}' references unknown host network '{network}'."
                )
        for os_type, provider_id in host["defaults"].get("filesystem_interface_by_guest_os", {}).items():
            if provider_id not in host["mountable_resource_interfaces"]:
                raise ConfigurationValidationError(
                    f"Default filesystem interface for guest OS '{os_type}' references unknown provider '{provider_id}'."
                )

    def _validate_guest(self, guest: dict[str, Any]) -> None:
        resources = guest["mountable_resources"]["items"]
        for relation in guest["mountable_resources"]["relations"]:
            for resource_id in relation["mountable_resources"]:
                if resource_id not in resources:
                    raise ConfigurationValidationError(
                        f"Guest relation '{relation['display_name']}' references unknown mountable resource '{resource_id}'."
                    )
        cpu = guest["compute"].get("cpu", {})
        if "minimum" in cpu and "default" in cpu and cpu["default"] < cpu["minimum"]:
            raise ConfigurationValidationError("Guest compute.cpu.default cannot be smaller than compute.cpu.minimum.")
        memory = guest["compute"].get("memory", {})
        if "minimum" in memory and "default" in memory and size_to_bytes(memory["default"]) < size_to_bytes(memory["minimum"]):
            raise ConfigurationValidationError("Guest compute.memory.default cannot be smaller than compute.memory.minimum.")
        for resource_id, resource in resources.items():
            capacity = resource.get("capacity", {})
            if "minimum" in capacity and "default" in capacity and size_to_bytes(capacity["default"]) < size_to_bytes(capacity["minimum"]):
                raise ConfigurationValidationError(
                    f"Mountable resource '{resource_id}' capacity.default cannot be smaller than capacity.minimum."
                )

    def _validate_compute(self, deployment: dict[str, Any], guest: dict[str, Any]) -> None:
        resolved = self._resolve_compute(deployment, guest)
        guest_cpu = guest["compute"].get("cpu", {})
        if "minimum" in guest_cpu and resolved["cpu"] < guest_cpu["minimum"]:
            raise ConfigurationValidationError(
                f"Deployment CPU {resolved['cpu']} is below guest minimum {guest_cpu['minimum']}."
            )
        guest_memory = guest["compute"].get("memory", {})
        if "minimum" in guest_memory and size_to_bytes(resolved["memory"]) < size_to_bytes(guest_memory["minimum"]):
            raise ConfigurationValidationError(
                f"Deployment memory {resolved['memory']} is below guest minimum {guest_memory['minimum']}."
            )

    @staticmethod
    def _resolve_compute(deployment: dict[str, Any], guest: dict[str, Any]) -> dict[str, Any]:
        dep_compute = deployment["compute"]
        guest_compute = guest["compute"]
        cpu = dep_compute.get("cpu")
        if cpu is None:
            cpu = guest_compute.get("cpu", {}).get("default") or guest_compute.get("cpu", {}).get("minimum")
        memory = dep_compute.get("memory")
        if memory is None:
            memory = guest_compute.get("memory", {}).get("default") or guest_compute.get("memory", {}).get("minimum")
        if cpu is None or memory is None:
            raise ConfigurationValidationError(
                "Deployment compute values are missing and the guest does not provide defaults/minimums for both CPU and memory."
            )
        return {"cpu": cpu, "memory": memory}

    def _resolve_networks(self, deployment: dict[str, Any], guest: dict[str, Any], host: dict[str, Any]) -> dict[str, Any]:
        guest_items = guest["network_interfaces"]["items"]
        bindings = deployment["network_interfaces"]["items"]
        unknown = set(bindings) - set(guest_items)
        if unknown:
            raise ConfigurationValidationError(
                f"Deployment binds unknown guest network interface(s): {', '.join(sorted(unknown))}."
            )
        for interface_id, definition in guest_items.items():
            if definition.get("required", True) and interface_id not in bindings:
                raise ConfigurationValidationError(
                    f"Required guest network interface '{interface_id}' has no deployment binding."
                )

        result: dict[str, Any] = {}
        for interface_id, binding in bindings.items():
            network_id = binding["host_network"]
            if network_id not in host["networks"]:
                raise ConfigurationValidationError(
                    f"Network interface '{interface_id}' references unknown host network '{network_id}'."
                )
            network = host["networks"][network_id]
            self._validate_ip_binding(interface_id, "ipv4", binding.get("ipv4"), network.get("subnet"), 4)
            self._validate_ip_binding(interface_id, "ipv6", binding.get("ipv6"), network.get("ipv6_subnet"), 6)
            resolved = {
                "display_name": guest_items[interface_id]["display_name"],
                "description": guest_items[interface_id]["description"],
                "host_network": network_id,
            }
            for key in ("ipv4", "ipv6", "mac_address"):
                if key in binding:
                    resolved[key] = binding[key]
            result[interface_id] = resolved
        return result

    @staticmethod
    def _validate_ip_binding(interface_id: str, field: str, address: str | None, subnet: str | None, version: int) -> None:
        if address is None:
            return
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ConfigurationValidationError(
                f"Network interface '{interface_id}' has invalid {field} address '{address}'."
            ) from exc
        if ip.version != version:
            raise ConfigurationValidationError(
                f"Network interface '{interface_id}' field {field} contains IPv{ip.version} address '{address}'."
            )
        if subnet:
            try:
                network = ipaddress.ip_network(subnet, strict=False)
            except ValueError as exc:
                raise ConfigurationValidationError(f"Host network has invalid subnet '{subnet}'.") from exc
            if ip not in network:
                raise ConfigurationValidationError(
                    f"Network interface '{interface_id}' address '{address}' is outside subnet '{subnet}'."
                )

    def _resolve_resources(
        self,
        deployment_entry: ConfigurationEntry,
        deployment: dict[str, Any],
        guest: dict[str, Any],
        host_entry: ConfigurationEntry,
        host: dict[str, Any],
        environment_entry: ConfigurationEntry,
        environment: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, PlacementFacts]]:
        guest_resources = guest["mountable_resources"]["items"]
        bindings = deployment["mountable_resources"]["items"]
        if set(bindings) != set(guest_resources):
            missing = sorted(set(guest_resources) - set(bindings))
            extra = sorted(set(bindings) - set(guest_resources))
            details = []
            if missing:
                details.append("missing: " + ", ".join(missing))
            if extra:
                details.append("unknown: " + ", ".join(extra))
            raise ConfigurationValidationError(
                "Deployment mountable-resource bindings do not match guest resources (" + "; ".join(details) + ")."
            )

        resolved: dict[str, Any] = {}
        facts: dict[str, PlacementFacts] = {}
        for resource_id, requirement in guest_resources.items():
            binding = bindings[resource_id]
            if "shared_mountable_resource" in binding:
                if requirement["sharing"] != "SHARED":
                    raise ConfigurationValidationError(
                        f"Exclusive mountable resource '{resource_id}' cannot use shared backing."
                    )
                resource, fact = self._resolve_shared_resource(
                    resource_id, requirement, binding, guest["os"]["type"], deployment
                )
            else:
                if requirement["sharing"] != "EXCLUSIVE":
                    raise ConfigurationValidationError(
                        f"Shared mountable resource '{resource_id}' must bind a SharedMountableResourceConfiguration."
                    )
                resource, fact = self._resolve_direct_resource(
                    deployment_entry, resource_id, requirement, binding,
                    host_entry, host, environment_entry, environment, guest["os"]["type"], deployment
                )
            resolved[resource_id] = resource
            facts[resource_id] = fact
        return resolved, facts

    def _resolve_direct_resource(
        self,
        deployment_entry: ConfigurationEntry,
        resource_id: str,
        requirement: dict[str, Any],
        binding: dict[str, Any],
        host_entry: ConfigurationEntry,
        host: dict[str, Any],
        environment_entry: ConfigurationEntry,
        environment: dict[str, Any],
        guest_os: str,
        deployment: dict[str, Any],
    ) -> tuple[dict[str, Any], PlacementFacts]:
        target_id = binding["host_storage_target"]
        target = self._compatible_target(host, target_id, requirement["storage_class"], requirement["representation"])
        size = binding.get("size") or requirement.get("capacity", {}).get("default")
        minimum = requirement.get("capacity", {}).get("minimum")
        if minimum and size and size_to_bytes(size) < size_to_bytes(minimum):
            raise ConfigurationValidationError(
                f"Mountable resource '{resource_id}' size {size} is below minimum {minimum}."
            )
        backend_definition = self._select_backend(target, requirement["representation"], binding.get("backend"))
        backend = self._materialize_backend(
            backend_definition, deployment_entry.reference, resource_id, shared=False
        )
        storage_identity = self._storage_identity(target, host_entry.reference)
        result = self._base_resolved_resource(requirement, target_id, storage_identity, backend, size)
        if requirement["representation"] == "FILESYSTEM":
            result["interface"] = self._resolve_interface(
                host,
                requirement,
                binding.get("host_mountable_resource_interface"),
                guest_os,
                backend,
                deployment_entry.reference,
                resource_id,
                shared=False,
                deployment=deployment,
            )
        fact = self._placement_facts(
            resource_id, host_entry.reference, host, environment_entry.reference, environment, target_id, target
        )
        return result, fact

    def _resolve_shared_resource(
        self,
        resource_id: str,
        requirement: dict[str, Any],
        binding: dict[str, Any],
        guest_os: str,
        deployment: dict[str, Any],
    ) -> tuple[dict[str, Any], PlacementFacts]:
        shared_entry, shared = self.repository.resolve(
            "shared_mountable_resources", binding["shared_mountable_resource"]
        )
        host_entry, host = self.repository.resolve("hosts", shared["host"])
        environment_entry, environment = self.repository.resolve("environments", host["environment"])
        self._validate_environment(environment)
        self._validate_host(host_entry, host, environment_entry, environment)

        if shared["storage_class"] != requirement["storage_class"]:
            raise ConfigurationValidationError(
                f"Shared backing '{shared_entry.reference}' storage class {shared['storage_class']} does not match "
                f"guest resource '{resource_id}' requirement {requirement['storage_class']}."
            )
        if shared["representation"] != requirement["representation"]:
            raise ConfigurationValidationError(
                f"Shared backing '{shared_entry.reference}' representation {shared['representation']} does not match "
                f"guest resource '{resource_id}' requirement {requirement['representation']}."
            )
        target_id = shared["host_storage_target"]
        target = self._compatible_target(host, target_id, shared["storage_class"], shared["representation"])
        backend_definition = self._select_backend(target, shared["representation"], shared.get("backend"))
        backend = self._materialize_backend(backend_definition, shared_entry.reference, shared["shared_mountable_resource"]["id"], shared=True)
        size = shared.get("size")
        minimum = requirement.get("capacity", {}).get("minimum")
        if size and minimum and size_to_bytes(size) < size_to_bytes(minimum):
            raise ConfigurationValidationError(
                f"Shared backing '{shared_entry.reference}' size {size} is below guest resource '{resource_id}' minimum {minimum}."
            )
        storage_identity = self._storage_identity(target, host_entry.reference)
        result = self._base_resolved_resource(requirement, target_id, storage_identity, backend, size)
        result["shared_mountable_resource"] = shared_entry.reference
        if requirement["representation"] == "FILESYSTEM":
            provider_id = shared.get("host_mountable_resource_interface")
            result["interface"] = self._resolve_interface(
                host, requirement, provider_id, guest_os, backend, shared_entry.reference,
                shared["shared_mountable_resource"]["id"], shared=True, deployment=deployment
            )
        fact = self._placement_facts(
            resource_id, host_entry.reference, host, environment_entry.reference, environment, target_id, target
        )
        return result, fact

    @staticmethod
    def _base_resolved_resource(
        requirement: dict[str, Any], target_id: str, storage_identity: str, backend: dict[str, Any], size: str | None
    ) -> dict[str, Any]:
        result = {
            "display_name": requirement["display_name"],
            "description": requirement["description"],
            "storage_class": requirement["storage_class"],
            "purpose": requirement["purpose"],
            "representation": requirement["representation"],
            "access": requirement["access"],
            "sharing": requirement["sharing"],
            "mount_point": requirement["mount_point"],
        }
        if size is not None:
            result["size"] = size
        result["host_storage_target"] = target_id
        result["storage_system"] = storage_identity
        result["backend"] = backend
        return result

    @staticmethod
    def _compatible_target(host: dict[str, Any], target_id: str, storage_class: str, representation: str) -> dict[str, Any]:
        try:
            target = host["storage_targets"][target_id]
        except KeyError as exc:
            raise ConfigurationValidationError(f"Unknown host storage target '{target_id}'.") from exc
        if target["storage_class"] != storage_class:
            raise ConfigurationValidationError(
                f"Host storage target '{target_id}' provides {target['storage_class']}, required {storage_class}."
            )
        if not any(item["type"] == representation for item in target["supported_representations"]):
            raise ConfigurationValidationError(
                f"Host storage target '{target_id}' does not support representation {representation}."
            )
        return target

    @staticmethod
    def _select_backend(target: dict[str, Any], representation: str, requested: str | None) -> dict[str, Any]:
        rep = next(item for item in target["supported_representations"] if item["type"] == representation)
        backends = rep["supported_backends"]
        if requested is None:
            return backends[0]
        for backend in backends:
            if backend["type"] == requested:
                return backend
        raise ConfigurationValidationError(
            f"Requested backend {requested} is not supported by target '{target.get('display_name', '<unknown>')}' "
            f"for representation {representation}."
        )

    @staticmethod
    def _materialize_backend(definition: dict[str, Any], owner_reference: str, resource_id: str, shared: bool) -> dict[str, Any]:
        backend_type = definition["type"]
        owner_id = PurePosixPath(owner_reference).name
        if backend_type == "QCOW2":
            path = PurePosixPath(definition["directory"]) / ("shared" if shared else owner_id)
            path = path / (f"{resource_id}.qcow2")
        elif backend_type == "RAW_FILE":
            path = PurePosixPath(definition["directory"]) / ("shared" if shared else owner_id)
            path = path / (f"{resource_id}.raw")
        elif backend_type == "LVM":
            lv_name = f"shared-{resource_id}" if shared else f"{owner_id}-{resource_id}"
            path = PurePosixPath("/dev") / definition["volume_group"] / lv_name
        elif backend_type == "DIRECTORY":
            path = PurePosixPath(definition["directory"]) / ("shared" if shared else owner_id) / resource_id
        else:
            raise ResolutionError(f"Unsupported backend type '{backend_type}'.")
        return {"type": backend_type, "path": str(path)}

    def _resolve_interface(
        self,
        host: dict[str, Any],
        requirement: dict[str, Any],
        requested_provider: str | None,
        guest_os: str | None,
        backend: dict[str, Any],
        owner_reference: str,
        resource_id: str,
        shared: bool,
        deployment: dict[str, Any] | None,
    ) -> dict[str, Any]:
        providers = host["mountable_resource_interfaces"]
        provider_id = requested_provider
        if provider_id is None and guest_os is not None:
            provider_id = host["defaults"].get("filesystem_interface_by_guest_os", {}).get(guest_os)
        required_type = requirement.get("required_interface")
        if provider_id is None:
            compatible = [pid for pid, provider in providers.items() if required_type is None or provider["type"] == required_type]
            if not compatible:
                raise ConfigurationValidationError("No compatible host filesystem interface provider is available.")
            provider_id = compatible[0]
        if provider_id not in providers:
            raise ConfigurationValidationError(f"Unknown host mountable-resource interface '{provider_id}'.")
        provider = providers[provider_id]
        if required_type and provider["type"] != required_type:
            raise ConfigurationValidationError(
                f"Filesystem provider '{provider_id}' has type {provider['type']}, required {required_type}."
            )
        provider_type = provider["type"]
        result: dict[str, Any] = {"provider": provider_id, "type": provider_type}
        owner_id = PurePosixPath(owner_reference).name
        export_path = f"/shared/{resource_id}" if shared else f"/{owner_id}/{resource_id}"
        if provider_type in ("NFS", "SAMBA"):
            result["server_address"] = provider["server_address"]
            result["export"] = export_path
            if deployment is not None:
                bound_networks = {
                    binding["host_network"] for binding in deployment["network_interfaces"]["items"].values()
                }
                if provider["host_network"] not in bound_networks:
                    raise ConfigurationValidationError(
                        f"Filesystem provider '{provider_id}' is exposed on host network '{provider['host_network']}', "
                        "but the deployment has no guest interface bound to that network."
                    )
        elif provider_type == "VIRTIOFS":
            result["source_path"] = backend["path"]
            result["tag"] = ("shared-" if shared else f"{owner_id}-") + resource_id
        return result

    @staticmethod
    def _storage_identity(target: dict[str, Any], host_reference: str) -> str:
        storage = target["storage_system"]
        return f"HOST_LOCAL_STORAGE@{host_reference}" if storage == "HOST_LOCAL_STORAGE" else storage

    def _placement_facts(
        self,
        resource_id: str,
        host_reference: str,
        host: dict[str, Any],
        environment_reference: str,
        environment: dict[str, Any],
        target_id: str,
        target: dict[str, Any],
    ) -> PlacementFacts:
        storage = target["storage_system"]
        env_id = environment["environment"]["id"]
        if storage == "HOST_LOCAL_STORAGE":
            host_id = host["host"]["id"]
            site = environment["hosts"][host_id]["site"]
            dependency_hosts = {f"{environment_reference}:{host_id}"}
            dependency_sites = {f"{environment_reference}:{site}"}
        else:
            storage_def = environment["storage_systems"][storage]
            impacted_hosts = storage_def.get("impacted_hosts")
            dependency_hosts = (
                {f"{environment_reference}:{host_id}" for host_id in impacted_hosts}
                if impacted_hosts is not None else None
            )
            sites = set(storage_def.get("impacted_sites", []))
            for host_id in storage_def.get("impacted_hosts", []):
                sites.add(environment["hosts"][host_id]["site"])
            dependency_sites = {f"{environment_reference}:{site}" for site in sites} if sites else None
        return PlacementFacts(
            resource_id=resource_id,
            host_reference=host_reference,
            host=host,
            environment_reference=environment_reference,
            environment=environment,
            target_id=target_id,
            target=target,
            storage_identity=self._storage_identity(target, host_reference),
            dependency_hosts=dependency_hosts,
            dependency_sites=dependency_sites,
        )

    def _resolve_relations(self, guest: dict[str, Any], facts: dict[str, PlacementFacts]) -> tuple[list[dict[str, Any]], list[str]]:
        results: list[dict[str, Any]] = []
        warnings: list[str] = []
        for relation in guest["mountable_resources"]["relations"]:
            selected = [facts[resource_id] for resource_id in relation["mountable_resources"]]
            failures: list[str] = []
            for relation_type in relation["relations"]:
                ok, message = self._relation_holds(relation_type, selected)
                if not ok:
                    failures.append(f"{relation_type}: {message}")
            satisfied = not failures
            message = "All requested relation predicates are satisfied." if satisfied else "; ".join(failures)
            result = {
                "display_name": relation["display_name"],
                "description": relation["description"],
                "mountable_resources": relation["mountable_resources"],
                "relations": relation["relations"],
                "requirement": relation["requirement"],
                "satisfied": satisfied,
                "message": message,
            }
            results.append(result)
            if not satisfied:
                if relation["requirement"] == "REQUIRED":
                    raise ResolutionError(
                        f"Required mountable-resource relation '{relation['display_name']}' is not satisfied: {message}"
                    )
                warning = f"Preferred mountable-resource relation '{relation['display_name']}' is not satisfied: {message}"
                warnings.append(warning)
                self.logger.warning(warning)
        return results, warnings

    def _relation_holds(self, relation_type: str, facts: list[PlacementFacts]) -> tuple[bool, str]:
        for index, left in enumerate(facts):
            for right in facts[index + 1 :]:
                ok, reason = self._pair_holds(relation_type, left, right)
                if not ok:
                    return False, f"{left.resource_id} vs {right.resource_id}: {reason}"
        return True, "pairwise relation satisfied"

    @staticmethod
    def _pair_holds(relation_type: str, left: PlacementFacts, right: PlacementFacts) -> tuple[bool, str]:
        if relation_type == "NO_SHARED_STORAGE_SYSTEM":
            return (left.storage_identity != right.storage_identity,
                    f"storage identities are '{left.storage_identity}' and '{right.storage_identity}'")
        if relation_type == "NO_SHARED_DEVICE":
            if left.host_reference != right.host_reference:
                return True, "resources are realized by different hosts"
            lset = left.target.get("impacted_devices")
            rset = right.target.get("impacted_devices")
            if lset is None or rset is None:
                return False, "device topology is unknown for at least one storage target"
            shared = set(lset) & set(rset)
            return (not shared, f"shared impacted devices: {', '.join(sorted(shared))}" if shared else "no shared impacted devices")
        if relation_type == "NO_SHARED_CONTROLLER":
            if left.host_reference != right.host_reference:
                return True, "resources are realized by different hosts"
            lset = left.target.get("impacted_controllers")
            rset = right.target.get("impacted_controllers")
            if lset is None or rset is None:
                return False, "controller topology is unknown for at least one storage target"
            shared = set(lset) & set(rset)
            return (not shared, f"shared impacted controllers: {', '.join(sorted(shared))}" if shared else "no shared impacted controllers")
        if relation_type == "NO_SHARED_HOST":
            if left.dependency_hosts is None or right.dependency_hosts is None:
                return False, "backing-host topology is unknown for at least one storage system"
            shared = left.dependency_hosts & right.dependency_hosts
            return (not shared, f"shared backing hosts: {', '.join(sorted(shared))}" if shared else "no shared backing hosts")
        if relation_type == "NO_SHARED_SITE":
            if left.dependency_sites is None or right.dependency_sites is None:
                return False, "site topology is unknown for at least one storage system"
            shared = left.dependency_sites & right.dependency_sites
            return (not shared, f"shared sites: {', '.join(sorted(shared))}" if shared else "no shared sites")
        raise ResolutionError(f"Unsupported relation type '{relation_type}'.")
