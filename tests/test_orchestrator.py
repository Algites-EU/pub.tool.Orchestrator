from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from orchestrator.common.configuration import ConfigurationCategory, ConfigurationRepository
from orchestrator.common.errors import AmbiguousReferenceError, ConfigurationValidationError, ResolutionError, UnresolvedReferenceError
from orchestrator.deployment.resolver import DeploymentResolver
from orchestrator.deployment.validation import DeploymentConfigurationValidator, SchemaValidator


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "config"
MODEL = ROOT / "orchestrator" / "deployment" / "model"


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
        self.assertEqual(11, len(report["validated_files"]))

    def test_all_example_deployments_generate_schema_valid_plans(self):
        for deployment in (
            "example-guest-deployment",
            "example-cache-provider-deployment",
            "example-datacenter-guest-deployment",
        ):
            with self.subTest(deployment=deployment):
                repo = self.repository()
                plan = DeploymentResolver(repo, self.schema).resolve(deployment)
                self.assertEqual(deployment, plan["deployment"])
                self.assertIn("resolved_mountable_resources", plan)

    def test_checked_in_example_plans_match_generator_output(self):
        for deployment in (
            "example-guest-deployment",
            "example-cache-provider-deployment",
            "example-datacenter-guest-deployment",
        ):
            with self.subTest(deployment=deployment):
                repo = self.repository()
                generated = DeploymentResolver(repo, self.schema).resolve(deployment)
                expected_path = ROOT / "examples" / "plans" / f"{deployment}.plan.yml"
                expected = yaml.safe_load(expected_path.read_text(encoding="utf-8"))
                self.assertEqual(expected, generated)

    def test_main_example_resolves_expected_backend_paths_and_relations(self):
        repo = self.repository()
        plan = DeploymentResolver(repo, self.schema).resolve("example-guest-deployment")
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
            (root / "hosts" / "site01").mkdir(parents=True)
            (root / "hosts" / "site02").mkdir(parents=True)
            for site in ("site01", "site02"):
                (root / "hosts" / site / "hostA.yml").write_text("host:\n  id: hostA\n", encoding="utf-8")
            repo = self.repository(root)
            self.assertEqual("site01/hostA", repo.resolve_entry("hosts", "site01/hostA").reference)
            with self.assertRaises(AmbiguousReferenceError) as cm:
                repo.resolve_entry("hosts", "hostA")
            self.assertIn("site01/hostA", str(cm.exception))
            self.assertIn("site02/hostA", str(cm.exception))

    def test_filename_must_equal_entity_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shutil.copytree(EXAMPLES, root / "config")
            path = root / "config" / "guests" / "example-guest.yml"
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            doc["guest"]["id"] = "different-id"
            path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
            repo = self.repository(root / "config")
            entry = repo.resolve_entry("guests", "example-guest")
            with self.assertRaises(ConfigurationValidationError):
                repo.load_entry(entry)

    def test_namespaced_references_are_accepted_by_schema_and_canonicalized_in_plan(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            (config / "hosts" / "site01").mkdir()
            shutil.move(config / "hosts" / "example-host.yml", config / "hosts" / "site01" / "example-host.yml")
            deployment_path = config / "deployments" / "example-guest-deployment.yml"
            deployment = yaml.safe_load(deployment_path.read_text(encoding="utf-8"))
            deployment["host"] = "site01/example-host"
            deployment_path.write_text(yaml.safe_dump(deployment, sort_keys=False), encoding="utf-8")
            for shared_name in ("shared-gradle-cache", "shared-nix-cache"):
                path = config / "shared-mountable-resources" / f"{shared_name}.yml"
                shared = yaml.safe_load(path.read_text(encoding="utf-8"))
                shared["host"] = "site01/example-host"
                path.write_text(yaml.safe_dump(shared, sort_keys=False), encoding="utf-8")
            cache_dep_path = config / "deployments" / "example-cache-provider-deployment.yml"
            cache_dep = yaml.safe_load(cache_dep_path.read_text(encoding="utf-8"))
            cache_dep["host"] = "site01/example-host"
            cache_dep_path.write_text(yaml.safe_dump(cache_dep, sort_keys=False), encoding="utf-8")

            repo = self.repository(config)
            plan = DeploymentResolver(repo, self.schema).resolve("example-guest-deployment")
            self.assertEqual("site01/example-host", plan["host"])
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

    def test_cli_keeps_result_on_stdout_and_diagnostics_on_stderr(self):
        proc = self.run_cli("cdp", f"-cr={EXAMPLES}", "-d=example-guest-deployment")
        self.assertEqual(0, proc.returncode, proc.stderr)
        plan = yaml.safe_load(proc.stdout)
        self.assertEqual("example-guest-deployment", plan["deployment"])
        self.assertNotIn("INFO", proc.stdout)
        self.assertIn("INFO Resolving deployment", proc.stderr)

    def test_processing_info_file_duplicates_stderr_and_relative_output_uses_output_folder(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td)
            proc = self.run_cli(
                "cdp", f"-cr={EXAMPLES}", "-d=example-guest-deployment",
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
                "cdp", f"-cr={EXAMPLES}", "-d=example-guest-deployment",
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
            duplicate = config / "guests" / "other" / "example-guest.yml"
            duplicate.parent.mkdir()
            shutil.copy2(config / "guests" / "example-guest.yml", duplicate)
            proc = self.run_cli("cdp", f"-cr={config}", "-d=example-guest-deployment", "-q")
            self.assertEqual(5, proc.returncode)
            self.assertIn("Ambiguous guests configuration reference", proc.stderr)
            self.assertIn("other/example-guest", proc.stderr)

    def test_preferred_relation_failure_becomes_warning_not_resolution_failure(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            host_path = config / "hosts" / "example-host.yml"
            host = yaml.safe_load(host_path.read_text(encoding="utf-8"))
            host["storage_targets"]["persistent-sata"]["impacted_devices"].append("nvme-a")
            host_path.write_text(yaml.safe_dump(host, sort_keys=False), encoding="utf-8")
            repo = self.repository(config)
            plan = DeploymentResolver(repo, self.schema).resolve("example-guest-deployment")
            self.assertEqual(1, len(plan["warnings"]))
            preferred = plan["relation_results"][0]
            self.assertFalse(preferred["satisfied"] )
            self.assertEqual("PREFERRED", preferred["requirement"])

    def test_required_relation_failure_stops_resolution(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"
            shutil.copytree(EXAMPLES, config)
            host_path = config / "hosts" / "example-host.yml"
            host = yaml.safe_load(host_path.read_text(encoding="utf-8"))
            host["storage_targets"]["archive-local-nas"]["storage_system"] = "HOST_LOCAL_STORAGE"
            host_path.write_text(yaml.safe_dump(host, sort_keys=False), encoding="utf-8")
            repo = self.repository(config)
            with self.assertRaises(ResolutionError):
                DeploymentResolver(repo, self.schema).resolve("example-guest-deployment")

    def test_reference_path_traversal_is_rejected(self):
        repo = self.repository()
        with self.assertRaises(UnresolvedReferenceError):
            repo.resolve_entry("hosts", "../example-host")
        with self.assertRaises(UnresolvedReferenceError):
            repo.resolve_entry("hosts", "/example-host")

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
                "vc", f"-cr={config}", "-d=example-datacenter-guest-deployment", "-q"
            )
            self.assertEqual(0, proc.returncode, proc.stderr)
            report = yaml.safe_load(proc.stdout)
            self.assertEqual("deployment", report["scope"])


if __name__ == "__main__":
    unittest.main()
