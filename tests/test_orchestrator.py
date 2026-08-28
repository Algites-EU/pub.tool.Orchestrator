from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

import yaml
from lxml import etree

from orchestrator.common.configuration import ConfigurationCategory, ConfigurationRepository
from orchestrator.common.errors import AmbiguousReferenceError, ConfigurationValidationError, ResolutionError, UnresolvedReferenceError
from orchestrator.common.io import serialize_xml
from orchestrator.deployment.resolver import DeploymentResolver
from orchestrator.deployment.validation import DeploymentConfigurationValidator, SchemaValidator


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "config"
MODEL = ROOT / "orchestrator" / "deployment" / "model"
VERSION = "1.0"


def categories() -> list[ConfigurationCategory]:
    return [
        ConfigurationCategory("deployments", "deployments", "guest-deployment-configuration.schema.yml", ("deployment", "id")),
        ConfigurationCategory("environments", "environments", "deployment-environment-configuration.schema.yml", ("environment", "id")),
        ConfigurationCategory("guests", "guests", "guest-configuration.schema.yml", ("guest", "id")),
        ConfigurationCategory("hosts", "hosts", "host-configuration.schema.yml", ("host", "id")),
        ConfigurationCategory(
            "shared_mountable_resources", "shared-mountable-resources",
            "shared-mountable-resource-configuration.schema.yml", ("shared_mountable_resource", "id")
        ),
        ConfigurationCategory("services", "services", "service-configuration.schema.yml", ("service", "id")),
    ]


class OrchestratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = SchemaValidator(MODEL)
        cls.schema.check_schemas()

    def repository(self, root: Path = EXAMPLES) -> ConfigurationRepository:
        return ConfigurationRepository(root, categories(), self.schema)

    def test_all_examples_validate(self):
        repo = self.repository()
        resolver = DeploymentResolver(repo, self.schema)
        report = DeploymentConfigurationValidator(repo, resolver).validate_all()
        self.assertTrue(report["valid"])
        self.assertEqual(12, len(report["validated_files"]))

    def test_all_example_deployments_generate_schema_valid_plans(self):
        for deployment in (
            "example-guest-deployment",
            "example-cache-provider-deployment",
            "example-datacenter-guest-deployment",
        ):
            with self.subTest(deployment=deployment):
                repo = self.repository()
                plan = DeploymentResolver(repo, self.schema).resolve(deployment, VERSION)
                self.assertEqual({"reference": deployment, "reference_config_version": VERSION}, plan["deployment"])
                self.assertIn("resolved_mountable_resources", plan)

    def test_checked_in_example_plans_match_generator_output(self):
        for deployment in (
            "example-guest-deployment",
            "example-cache-provider-deployment",
            "example-datacenter-guest-deployment",
        ):
            with self.subTest(deployment=deployment):
                repo = self.repository()
                generated = DeploymentResolver(repo, self.schema).resolve(deployment, VERSION)
                expected_path = ROOT / "examples" / "plans" / f"{deployment}.plan.yml"
                expected = yaml.safe_load(expected_path.read_text(encoding="utf-8"))
                self.assertEqual(expected, generated)

    def test_main_example_resolves_expected_backend_paths_and_relations(self):
        repo = self.repository()
        plan = DeploymentResolver(repo, self.schema).resolve("example-guest-deployment", VERSION)
        resources = plan["resolved_mountable_resources"]
        self.assertEqual(
            "/srv/libvirt/DISPOSABLE/qemu/images/example-guest-deployment/system-root.qcow2",
            resources["system-root"]["backend"]["path"],
        )
        self.assertEqual(
            "/dev/VG_NVME_RAID1/example-guest-deployment-application-data",
            resources["application-data"]["backend"]["path"],
        )
        self.assertEqual(
            "/srv/libvirt/PERSISTENT/share/shared/shared-nix-cache",
            resources["nix-cache"]["backend"]["path"],
        )
        self.assertTrue(all(item["satisfied"] for item in plan["relation_results"]))
        self.assertEqual([], plan["warnings"])

    def test_qualified_reference_is_exact_and_unqualified_reference_can_be_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for site in ("site01", "site02"):
                package = root / "hosts" / site / "hostA" / VERSION
                package.mkdir(parents=True)
                (package / f"hostA_{VERSION}.yml").write_text(
                    f"host:\n  id: hostA\n  config_version: '{VERSION}'\n", encoding="utf-8"
                )
            repo = self.repository(root)
            self.assertEqual("site01/hostA", repo.resolve_entry("hosts", "site01/hostA", VERSION).reference)
            with self.assertRaises(AmbiguousReferenceError) as cm:
                repo.resolve_entry("hosts", "hostA", VERSION)
            self.assertIn("site01/hostA", str(cm.exception))
            self.assertIn("site02/hostA", str(cm.exception))

    def test_filename_must_equal_entity_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shutil.copytree(EXAMPLES, root / "config")
            path = root / "config" / "guests" / "example-guest" / VERSION / f"example-guest_{VERSION}.yml"
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            doc["guest"]["id"] = "different-id"
            path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
            repo = self.repository(root / "config")
            entry = repo.resolve_entry("guests", "example-guest", VERSION)
            with self.assertRaises(ConfigurationValidationError):
                repo.load_entry(entry)

    def test_namespaced_references_are_accepted_by_schema_and_canonicalized_in_plan(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            (config / "hosts" / "site01").mkdir()
            shutil.move(config / "hosts" / "example-host", config / "hosts" / "site01" / "example-host")
            deployment_path = config / "deployments" / "example-guest-deployment" / VERSION / f"example-guest-deployment_{VERSION}.yml"
            deployment = yaml.safe_load(deployment_path.read_text(encoding="utf-8"))
            deployment["host"] = {"reference": "site01/example-host", "reference_config_version": VERSION}
            deployment_path.write_text(yaml.safe_dump(deployment, sort_keys=False), encoding="utf-8")
            for shared_name in ("shared-gradle-cache", "shared-nix-cache"):
                path = config / "shared-mountable-resources" / shared_name / VERSION / f"{shared_name}_{VERSION}.yml"
                shared = yaml.safe_load(path.read_text(encoding="utf-8"))
                shared["host"] = {"reference": "site01/example-host", "reference_config_version": VERSION}
                path.write_text(yaml.safe_dump(shared, sort_keys=False), encoding="utf-8")
            cache_dep_path = config / "deployments" / "example-cache-provider-deployment" / VERSION / f"example-cache-provider-deployment_{VERSION}.yml"
            cache_dep = yaml.safe_load(cache_dep_path.read_text(encoding="utf-8"))
            cache_dep["host"] = {"reference": "site01/example-host", "reference_config_version": VERSION}
            cache_dep_path.write_text(yaml.safe_dump(cache_dep, sort_keys=False), encoding="utf-8")

            repo = self.repository(config)
            plan = DeploymentResolver(repo, self.schema).resolve("example-guest-deployment", VERSION)
            self.assertEqual({"reference": "site01/example-host", "reference_config_version": VERSION}, plan["host"])
            self.assertEqual(
                "HOST_LOCAL_STORAGE@site01/example-host",
                plan["resolved_mountable_resources"]["application-data"]["storage_system"],
            )

    def run_cli(self, *args: str, cwd: Path | None = None):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT)
        return subprocess.run(
            [sys.executable, "-m", "orchestrator", *args],
            cwd=str(cwd or ROOT), env=env, text=True, capture_output=True, check=False
        )


    def run_cli_binary(self, *args: str, cwd: Path | None = None):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT)
        return subprocess.run(
            [sys.executable, "-m", "orchestrator", *args],
            cwd=str(cwd or ROOT), env=env, capture_output=True, check=False
        )

    def test_cli_keeps_result_on_stdout_and_diagnostics_on_stderr(self):
        proc = self.run_cli("cdp", f"-cr={EXAMPLES}", "-d=example-guest-deployment@1.0")
        self.assertEqual(0, proc.returncode, proc.stderr)
        plan = yaml.safe_load(proc.stdout)
        self.assertEqual({"reference": "example-guest-deployment", "reference_config_version": VERSION}, plan["deployment"])
        self.assertNotIn("INFO", proc.stdout)
        self.assertIn("INFO Resolving deployment", proc.stderr)

    def test_processing_info_file_duplicates_stderr_and_relative_output_uses_output_folder(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td)
            proc = self.run_cli(
                "cdp", f"-cr={EXAMPLES}", "-d=example-guest-deployment@1.0",
                f"-of={output}", "-ofn=plans/plan.yml", "-pifn=logs/processing.log"
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            self.assertEqual("", proc.stdout)
            self.assertTrue((output / "plans" / "plan.yml").is_file())
            processing = (output / "logs" / "processing.log").read_text(encoding="utf-8")
            self.assertIn("INFO Resolving deployment", processing)
            self.assertIn("INFO Resolving deployment", proc.stderr)

    def test_absolute_output_file_ignores_output_folder(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            actual = root / "absolute" / "plan.json"
            ignored = root / "ignored"
            proc = self.run_cli(
                "cdp", f"-cr={EXAMPLES}", "-d=example-guest-deployment@1.0",
                f"-of={ignored}", f"-ofn={actual}", "-ofmt=json", "-q"
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            self.assertTrue(actual.is_file())
            self.assertFalse((ignored / "plan.json").exists())
            self.assertEqual("", proc.stderr)

    def test_cli_ambiguity_has_exit_code_5(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            duplicate_package = config / "guests" / "other" / "example-guest"
            duplicate_package.parent.mkdir()
            shutil.copytree(config / "guests" / "example-guest", duplicate_package)
            proc = self.run_cli("cdp", f"-cr={config}", "-d=example-guest-deployment@1.0", "-q")
            self.assertEqual(5, proc.returncode)
            self.assertIn("Ambiguous guests configuration reference", proc.stderr)
            self.assertIn("other/example-guest", proc.stderr)

    def test_preferred_relation_failure_becomes_warning_not_resolution_failure(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            host_path = config / "hosts" / "example-host" / VERSION / f"example-host_{VERSION}.yml"
            host = yaml.safe_load(host_path.read_text(encoding="utf-8"))
            host["storage_targets"]["persistent-sata"]["impacted_devices"].append("nvme-a")
            host_path.write_text(yaml.safe_dump(host, sort_keys=False), encoding="utf-8")
            repo = self.repository(config)
            plan = DeploymentResolver(repo, self.schema).resolve("example-guest-deployment", VERSION)
            self.assertEqual(1, len(plan["warnings"]))
            preferred = plan["relation_results"][0]
            self.assertFalse(preferred["satisfied"] )
            self.assertEqual("PREFERRED", preferred["requirement"])

    def test_required_relation_failure_stops_resolution(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            host_path = config / "hosts" / "example-host" / VERSION / f"example-host_{VERSION}.yml"
            host = yaml.safe_load(host_path.read_text(encoding="utf-8"))
            host["storage_targets"]["archive-local-nas"]["storage_system"] = "HOST_LOCAL_STORAGE"
            host_path.write_text(yaml.safe_dump(host, sort_keys=False), encoding="utf-8")
            repo = self.repository(config)
            with self.assertRaises(ResolutionError):
                DeploymentResolver(repo, self.schema).resolve("example-guest-deployment", VERSION)

    def test_reference_path_traversal_is_rejected(self):
        repo = self.repository()
        with self.assertRaises(UnresolvedReferenceError):
            repo.resolve_entry("hosts", "../example-host", VERSION)
        with self.assertRaises(UnresolvedReferenceError):
            repo.resolve_entry("hosts", "/example-host", VERSION)

    def test_yaml_extension_is_rejected_by_full_validation(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            (config / "guests" / "ignored.yaml").write_text("guest: ignored\n", encoding="utf-8")
            repo = self.repository(config)
            resolver = DeploymentResolver(repo, self.schema)
            with self.assertRaises(ConfigurationValidationError):
                DeploymentConfigurationValidator(repo, resolver).validate_all()

    def test_validation_closure_does_not_parse_unrelated_invalid_configuration(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            unrelated = config / "guests" / "unrelated.yml"
            unrelated.write_text("this: [is: invalid", encoding="utf-8")
            proc = self.run_cli(
                "vc", f"-cr={config}", "-d=example-datacenter-guest-deployment@1.0", "-q"
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            report = yaml.safe_load(proc.stdout)
            self.assertEqual("deployment", report["scope"])


    def test_plan_contains_environment_and_resolved_operating_systems(self):
        plan = DeploymentResolver(self.repository(), self.schema).resolve("example-guest-deployment", VERSION)
        self.assertEqual({"reference": "example-environment", "reference_config_version": VERSION}, plan["environment"])
        self.assertEqual({"type": "NIXOS"}, plan["resolved_os"])
        self.assertEqual({"type": "DEBIAN"}, plan["resolved_host_os"])

    def test_configuration_entity_package_layout_is_required(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            package = config / "guests" / "example-guest"
            definition = package / VERSION / f"example-guest_{VERSION}.yml"
            flat = config / "guests" / "example-guest.yml"
            definition.rename(flat)
            shutil.rmtree(package)
            repo = self.repository(config)
            resolver = DeploymentResolver(repo, self.schema)
            with self.assertRaises(ConfigurationValidationError):
                DeploymentConfigurationValidator(repo, resolver).validate_all()

    def test_guest_os_implementation_directory_must_exist_inside_entity_package(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            shutil.rmtree(config / "guests" / "example-guest" / VERSION / "nixos")
            repo = self.repository(config)
            with self.assertRaises(ConfigurationValidationError):
                DeploymentResolver(repo, self.schema).resolve("example-guest-deployment", VERSION)


    def test_management_endpoint_is_resolved_from_guest_interface_binding(self):
        plan = DeploymentResolver(self.repository(), self.schema).resolve("example-guest-deployment", VERSION)
        endpoint = plan["resolved_management_endpoint"]
        self.assertEqual("172.27.130.50", endpoint["address"])
        self.assertEqual(
            {"application_protocol": "SSH", "transport_protocol": "TCP", "port": 22},
            endpoint["service_binding"],
        )

    def test_dual_stack_management_binding_requires_address_family(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            path = config / "deployments" / "example-datacenter-guest-deployment" / VERSION / f"example-datacenter-guest-deployment_{VERSION}.yml"
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            doc["management_endpoint_interface_binding"].pop("address_family")
            path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
            repo = self.repository(config)
            with self.assertRaises(ConfigurationValidationError) as cm:
                DeploymentResolver(repo, self.schema).resolve("example-datacenter-guest-deployment", VERSION)
            self.assertIn("dual-stack", str(cm.exception))


    def test_parallel_configuration_versions_resolve_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            entity = config / "guests" / "example-guest"
            source = entity / VERSION
            target_version = "2.0"
            target = entity / target_version
            shutil.copytree(source, target)
            old_file = target / f"example-guest_{VERSION}.yml"
            new_file = target / f"example-guest_{target_version}.yml"
            old_file.rename(new_file)
            doc = yaml.safe_load(new_file.read_text(encoding="utf-8"))
            doc["guest"]["config_version"] = target_version
            new_file.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
            repo = self.repository(config)
            self.assertEqual(VERSION, repo.resolve_entry("guests", "example-guest", VERSION).config_version)
            self.assertEqual(target_version, repo.resolve_entry("guests", "example-guest", target_version).config_version)

    def test_allowed_config_version_state_checks_entire_resolved_closure(self):
        proc = self.run_cli(
            "cdp", f"-cr={EXAMPLES}", "-d=example-guest-deployment@1.0",
            "--allow-config-version-state=RELEASED", "-q"
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            service_path = config / "services" / "example-artifact-cache" / VERSION / f"example-artifact-cache_{VERSION}.yml"
            doc = yaml.safe_load(service_path.read_text(encoding="utf-8"))
            doc["service"]["config_version_state"] = "DEVELOPMENT"
            service_path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
            proc = self.run_cli(
                "cdp", f"-cr={config}", "-d=example-guest-deployment@1.0",
                "--allow-config-version-state=RELEASED", "-q"
            )
            self.assertEqual(3, proc.returncode)
            self.assertIn("services:example-artifact-cache@1.0", proc.stderr)
            self.assertIn("DEVELOPMENT", proc.stderr)

    def test_service_package_requires_common_consumer_provider_directories(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            shutil.rmtree(config / "services" / "example-artifact-cache" / VERSION / "provider")
            repo = self.repository(config)
            with self.assertRaises(ConfigurationValidationError) as cm:
                repo.resolve("services", {"reference": "example-artifact-cache", "reference_config_version": VERSION})
            self.assertIn("common/, consumer/ and provider/", str(cm.exception))

    def test_host_debian_implementation_directory_must_exist_inside_entity_package(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            shutil.rmtree(config / "hosts" / "example-host" / VERSION / "debian")
            repo = self.repository(config)
            with self.assertRaises(ConfigurationValidationError) as cm:
                DeploymentResolver(repo, self.schema).resolve("example-guest-deployment", VERSION)
            self.assertIn("declares operating system DEBIAN", str(cm.exception))
            self.assertIn("debian/", str(cm.exception))

    def test_service_implementation_is_selected_by_target_operating_system(self):
        plan = DeploymentResolver(self.repository(), self.schema).resolve("example-guest-deployment", VERSION)
        guest_service = plan["resolved_services"]["guest_consumed"]["artifact-cache"]
        self.assertEqual("NIXOS", guest_service["implementation"]["os_type"])
        self.assertEqual("common/nixos/", guest_service["implementation"]["common_path"])
        self.assertEqual("consumer/nixos/", guest_service["implementation"]["role_path"])
        host_service = plan["resolved_services"]["host_consumed"]["artifact-cache"]
        self.assertEqual("DEBIAN", host_service["implementation"]["os_type"])
        self.assertEqual("common/debian/", host_service["implementation"]["common_path"])
        self.assertEqual("consumer/debian/", host_service["implementation"]["role_path"])

    def test_service_role_requires_matching_operating_system_implementation(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            shutil.rmtree(config / "services" / "example-artifact-cache" / VERSION / "consumer" / "debian")
            repo = self.repository(config)
            with self.assertRaises(ConfigurationValidationError) as cm:
                DeploymentResolver(repo, self.schema).resolve("example-guest-deployment", VERSION)
            self.assertIn("consumer implementation for operating system DEBIAN", str(cm.exception))
            self.assertIn("consumer/debian/", str(cm.exception))

    def test_service_branch_rejects_definition_files_outside_os_subdirectory(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            bad = config / "services" / "example-artifact-cache" / VERSION / "consumer" / "default.nix"
            bad.write_text("{ ... }: {}\n", encoding="utf-8")
            repo = self.repository(config)
            with self.assertRaises(ConfigurationValidationError) as cm:
                repo.resolve("services", {"reference": "example-artifact-cache", "reference_config_version": VERSION})
            self.assertIn("operating-system subdirectory", str(cm.exception))

    def test_cross_entity_reference_requires_reference_config_version(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            path = config / "deployments" / "example-guest-deployment" / VERSION / f"example-guest-deployment_{VERSION}.yml"
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            doc["guest"].pop("reference_config_version")
            path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
            with self.assertRaises(ConfigurationValidationError):
                DeploymentResolver(self.repository(config), self.schema).resolve("example-guest-deployment", VERSION)

    def test_all_configuration_xml_equivalents_match_xsd_1_0(self):
        mappings = {
            "environments": ("deployment-environment-configuration", "deployment-environment-configuration.xsd"),
            "hosts": ("host-configuration", "host-configuration.xsd"),
            "guests": ("guest-configuration", "guest-configuration.xsd"),
            "deployments": ("guest-deployment-configuration", "guest-deployment-configuration.xsd"),
            "shared-mountable-resources": (
                "shared-mountable-resource-configuration",
                "shared-mountable-resource-configuration.xsd",
            ),
            "services": ("service-configuration", "service-configuration.xsd"),
        }
        for category, (root_name, schema_name) in mappings.items():
            schema = etree.XMLSchema(etree.parse(str(MODEL / schema_name)))
            for path in sorted((EXAMPLES / category).rglob("*.yml")):
                with self.subTest(path=path):
                    document = yaml.safe_load(path.read_text(encoding="utf-8"))
                    xml = etree.fromstring(serialize_xml(document, root_name).encode("utf-8"))
                    self.assertTrue(schema.validate(xml), schema.error_log)

    def test_cdp_supports_xml_and_xml_matches_xsd(self):
        proc = self.run_cli(
            "cdp", f"-cr={EXAMPLES}", "-d=example-guest-deployment@1.0", "-ofmt=xml", "-q"
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        document = etree.fromstring(proc.stdout.encode("utf-8"))
        self.assertEqual("deployment-plan", document.tag)
        self.assertEqual("example-guest-deployment", document.findtext("deployment/reference"))
        schema = etree.XMLSchema(etree.parse(str(MODEL / "deployment-plan.xsd")))
        self.assertTrue(schema.validate(document), schema.error_log)

    def test_validation_report_supports_xml_and_matches_xsd(self):
        proc = self.run_cli("vc", f"-cr={EXAMPLES}", "-d=example-guest-deployment@1.0", "-ofmt=xml", "-q")
        self.assertEqual(0, proc.returncode, proc.stderr)
        document = etree.fromstring(proc.stdout.encode("utf-8"))
        schema = etree.XMLSchema(etree.parse(str(MODEL / "validation-report.xsd")))
        self.assertTrue(schema.validate(document), schema.error_log)

    def test_cdb_stdout_is_zip_with_self_contained_yaml_deployment(self):
        proc = self.run_cli_binary(
            "cdb", f"-cr={EXAMPLES}", "-d=example-guest-deployment@1.0", "-q"
        )
        self.assertEqual(0, proc.returncode, proc.stderr.decode("utf-8"))
        with ZipFile(io.BytesIO(proc.stdout)) as archive:
            names = set(archive.namelist())
            self.assertIn("deployment-bundle/manifest.yml", names)
            self.assertIn(
                "deployment-bundle/deployments/example-guest-deployment/1.0/example-guest-deployment_1.0_deployment-plan.yml",
                names,
            )
            self.assertIn(
                "deployment-bundle/deployments/example-guest-deployment/1.0/guest/example-guest/1.0/example-guest_1.0.yml",
                names,
            )
            self.assertIn(
                "deployment-bundle/deployments/example-guest-deployment/1.0/guest/example-guest/1.0/nixos/default.nix",
                names,
            )
            self.assertIn(
                "deployment-bundle/deployments/example-guest-deployment/1.0/host/example-host/1.0/example-host_1.0.yml",
                names,
            )
            self.assertIn(
                "deployment-bundle/deployments/example-guest-deployment/1.0/host/example-host/1.0/debian/apt/packages.list",
                names,
            )
            self.assertIn(
                "deployment-bundle/deployments/example-guest-deployment/1.0/guest-deployment/example-guest-deployment/1.0/example-guest-deployment_1.0.yml",
                names,
            )
            self.assertIn(
                "deployment-bundle/deployments/example-guest-deployment/1.0/service/example-artifact-cache/1.0/example-artifact-cache_1.0.yml",
                names,
            )
            self.assertIn(
                "deployment-bundle/deployments/example-guest-deployment/1.0/service/example-artifact-cache/1.0/consumer/nixos/default.nix",
                names,
            )
            self.assertIn(
                "deployment-bundle/deployments/example-guest-deployment/1.0/service/example-artifact-cache/1.0/consumer/debian/apt/packages.list",
                names,
            )
            manifest = yaml.safe_load(archive.read("deployment-bundle/manifest.yml"))
            self.assertEqual("yaml", manifest["deployment_plan_format"])
            self.assertEqual(1, len(manifest["deployments"]))

    def test_cdb_can_contain_multiple_deployments_and_duplicate_dependencies_per_deployment(self):
        with tempfile.TemporaryDirectory() as td:
            bundle_path = Path(td) / "multi.zip"
            proc = self.run_cli(
                "cdb", f"-cr={EXAMPLES}",
                "-d=example-guest-deployment@1.0", "-d=example-cache-provider-deployment@1.0",
                f"-ofn={bundle_path}", "-q"
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            with ZipFile(bundle_path) as archive:
                names = set(archive.namelist())
                self.assertIn(
                    "deployment-bundle/deployments/example-guest-deployment/1.0/host/example-host/1.0/example-host_1.0.yml",
                    names,
                )
                self.assertIn(
                    "deployment-bundle/deployments/example-cache-provider-deployment/1.0/host/example-host/1.0/example-host_1.0.yml",
                    names,
                )
                manifest = yaml.safe_load(archive.read("deployment-bundle/manifest.yml"))
                self.assertEqual(2, len(manifest["deployments"]))

    def test_cdb_can_contain_two_versions_of_same_deployment(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            entity = config / "deployments" / "example-guest-deployment"
            target_version = "2.0"
            target = entity / target_version
            shutil.copytree(entity / VERSION, target)
            old_file = target / f"example-guest-deployment_{VERSION}.yml"
            new_file = target / f"example-guest-deployment_{target_version}.yml"
            old_file.rename(new_file)
            doc = yaml.safe_load(new_file.read_text(encoding="utf-8"))
            doc["deployment"]["config_version"] = target_version
            new_file.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
            bundle_path = Path(td) / "versions.zip"
            proc = self.run_cli(
                "cdb", f"-cr={config}",
                "-d=example-guest-deployment@1.0", "-d=example-guest-deployment@2.0",
                f"-ofn={bundle_path}", "-q"
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            with ZipFile(bundle_path) as archive:
                names = set(archive.namelist())
                self.assertIn(
                    "deployment-bundle/deployments/example-guest-deployment/1.0/example-guest-deployment_1.0_deployment-plan.yml",
                    names,
                )
                self.assertIn(
                    "deployment-bundle/deployments/example-guest-deployment/2.0/example-guest-deployment_2.0_deployment-plan.yml",
                    names,
                )

    def test_cdb_includes_selected_service_provider_implementation(self):
        with tempfile.TemporaryDirectory() as td:
            bundle_path = Path(td) / "provider.zip"
            proc = self.run_cli(
                "cdb", f"-cr={EXAMPLES}", "-d=example-cache-provider-deployment@1.0",
                f"-ofn={bundle_path}", "-q"
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            with ZipFile(bundle_path) as archive:
                names = set(archive.namelist())
                self.assertIn(
                    "deployment-bundle/deployments/example-cache-provider-deployment/1.0/service/example-artifact-cache/1.0/provider/nixos/default.nix",
                    names,
                )
                plan = yaml.safe_load(archive.read(
                    "deployment-bundle/deployments/example-cache-provider-deployment/1.0/example-cache-provider-deployment_1.0_deployment-plan.yml"
                ))
                implementation = plan["resolved_services"]["guest_provided"]["artifact-cache"]["implementation"]
                self.assertEqual("NIXOS", implementation["os_type"])
                self.assertEqual("provider/nixos/", implementation["role_path"])

    def test_cdb_json_format_applies_to_manifest_and_plans(self):
        with tempfile.TemporaryDirectory() as td:
            bundle_path = Path(td) / "bundle.zip"
            proc = self.run_cli(
                "cdb", f"-cr={EXAMPLES}", "-d=example-datacenter-guest-deployment@1.0",
                "-ofmt=json", f"-ofn={bundle_path}", "-q"
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            with ZipFile(bundle_path) as archive:
                manifest = json.loads(archive.read("deployment-bundle/manifest.json"))
                plan_path = "deployment-bundle/" + manifest["deployments"][0]["deployment_plan"]
                plan = json.loads(archive.read(plan_path))
                self.assertEqual("json", manifest["deployment_plan_format"])
                self.assertEqual({"reference": "example-datacenter-guest-deployment", "reference_config_version": VERSION}, plan["deployment"])

    def test_cdb_xml_manifest_and_plan_match_xsds(self):
        with tempfile.TemporaryDirectory() as td:
            bundle_path = Path(td) / "bundle.zip"
            proc = self.run_cli(
                "cdb", f"-cr={EXAMPLES}", "-d=example-guest-deployment@1.0",
                "-ofmt=xml", f"-ofn={bundle_path}", "-q"
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            with ZipFile(bundle_path) as archive:
                manifest_xml = etree.fromstring(archive.read("deployment-bundle/manifest.xml"))
                manifest_schema = etree.XMLSchema(etree.parse(str(MODEL / "deployment-bundle-manifest.xsd")))
                self.assertTrue(manifest_schema.validate(manifest_xml), manifest_schema.error_log)
                plan_path = manifest_xml.findtext("deployments/item/deployment_plan")
                plan_xml = etree.fromstring(archive.read("deployment-bundle/" + plan_path))
                plan_schema = etree.XMLSchema(etree.parse(str(MODEL / "deployment-plan.xsd")))
                self.assertTrue(plan_schema.validate(plan_xml), plan_schema.error_log)

    def test_cdb_rejects_duplicate_deployment_arguments(self):
        proc = self.run_cli(
            "cdb", f"-cr={EXAMPLES}", "-d=example-guest-deployment@1.0", "-d=example-guest-deployment@1.0", "-q"
        )
        self.assertEqual(2, proc.returncode)
        self.assertIn("same --deployment", proc.stderr)


if __name__ == "__main__":
    unittest.main()
