from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from orchestrator import __version__
from orchestrator.common.configuration import ConfigurationCategory, ConfigurationRepository
from orchestrator.common.errors import CliArgumentError, OrchestratorError
from orchestrator.common.io import resolve_output_path, write_binary_result, write_result
from orchestrator.common.logging import configure_processing_logger
from orchestrator.deployment.bundle import DeploymentBundleBuilder
from orchestrator.deployment.resolver import DeploymentResolver
from orchestrator.deployment.validation import DeploymentConfigurationValidator, SchemaValidator


class OrchestratorArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise CliArgumentError(message)


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config-root", "-cr", default=".", help="Configuration root directory (default: current directory).")
    parser.add_argument("--config-folder-deployments-name", "-cfdn", default="deployments")
    parser.add_argument("--config-folder-environments-name", "-cfen", default="environments")
    parser.add_argument("--config-folder-guests-name", "-cfgn", default="guests")
    parser.add_argument("--config-folder-hosts-name", "-cfhn", default="hosts")
    parser.add_argument(
        "--config-folder-shared-mountable-resources-name", "-cfsmrn", default="shared-mountable-resources"
    )
    parser.add_argument("--output-folder", "-of", help="Base folder for relative output file paths.")
    parser.add_argument("--output-file-name", "-ofn", help="Result file path. If omitted, result is written to stdout.")
    parser.add_argument(
        "--processing-info-file-name", "-pifn",
        help="Optional diagnostic log file; diagnostics are still written to stderr."
    )
    parser.add_argument("--output-format", "-ofmt", choices=("yaml", "json", "xml"), default="yaml")
    level_group = parser.add_mutually_exclusive_group()
    level_group.add_argument(
        "--log-level", "-ll", choices=("TRACE", "DEBUG", "INFO", "WARNING", "ERROR"),
        type=str.upper, default="INFO"
    )
    level_group.add_argument("--verbose", "-vb", action="store_true", help="Equivalent to --log-level=DEBUG.")
    level_group.add_argument("--quiet", "-q", action="store_true", help="Equivalent to --log-level=ERROR.")


def _build_parser() -> argparse.ArgumentParser:
    parser = OrchestratorArgumentParser(prog="algites-orchestrator", description="Algites Orchestrator CLI")
    parser.add_argument("--version", "-v", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    cdp = subparsers.add_parser("create-deployment-plan", aliases=["cdp"], help="Resolve one deployment into DeploymentPlan.")
    _add_common_options(cdp)
    cdp.add_argument("--deployment", "-d", required=True, help="Deployment configuration reference.")

    cdb = subparsers.add_parser(
        "create-deployment-bundle", aliases=["cdb"],
        help="Create a portable ZIP with one or more DeploymentPlans and all required Configuration Entity Packages."
    )
    _add_common_options(cdb)
    cdb.add_argument(
        "--deployment", "-d", required=True, action="append",
        help="Deployment configuration reference. Repeat the option to include multiple deployments."
    )

    vc = subparsers.add_parser("validate-configuration", aliases=["vc"], help="Validate configuration root or one deployment closure.")
    _add_common_options(vc)
    vc.add_argument("--deployment", "-d", help="Optional deployment reference limiting validation to its closure.")
    return parser


def _categories(args) -> list[ConfigurationCategory]:
    return [
        ConfigurationCategory("deployments", args.config_folder_deployments_name, "guest-deployment-configuration.schema.yml", ("deployment", "id")),
        ConfigurationCategory("environments", args.config_folder_environments_name, "deployment-environment-configuration.schema.yml", ("environment", "id")),
        ConfigurationCategory("guests", args.config_folder_guests_name, "guest-configuration.schema.yml", ("guest", "id")),
        ConfigurationCategory("hosts", args.config_folder_hosts_name, "host-configuration.schema.yml", ("host", "id")),
        ConfigurationCategory(
            "shared_mountable_resources", args.config_folder_shared_mountable_resources_name,
            "shared-mountable-resource-configuration.schema.yml", ("shared_mountable_resource", "id")
        ),
    ]


def _effective_log_level(args) -> str:
    if args.verbose:
        return "DEBUG"
    if args.quiet:
        return "ERROR"
    return args.log_level


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    logger: logging.Logger | None = None
    try:
        args = parser.parse_args(argv)
        output_path = resolve_output_path(args.output_file_name, args.output_folder)
        processing_path = resolve_output_path(args.processing_info_file_name, args.output_folder)
        if output_path is not None and processing_path is not None and output_path.resolve() == processing_path.resolve():
            raise CliArgumentError("Result output file and processing info file must be different paths.")
        logger = configure_processing_logger(_effective_log_level(args), processing_path)

        model_directory = Path(__file__).resolve().parent / "deployment" / "model"
        schema_validator = SchemaValidator(model_directory)
        schema_validator.check_schemas()
        repository = ConfigurationRepository(
            Path(args.config_root), _categories(args), schema_validator
        )
        resolver = DeploymentResolver(repository, schema_validator, logger)

        if args.command in ("create-deployment-plan", "cdp"):
            logger.info("Resolving deployment '%s'.", args.deployment)
            result = resolver.resolve(args.deployment)
            logger.info("Deployment plan resolved successfully for '%s'.", result["deployment"])
            write_result(result, args.output_format, output_path, "deployment-plan")

        elif args.command in ("create-deployment-bundle", "cdb"):
            if len(set(args.deployment)) != len(args.deployment):
                raise CliArgumentError("The same --deployment reference may not be specified more than once in one bundle.")
            builder = DeploymentBundleBuilder(repository, resolver, schema_validator, logger)
            bundle = builder.build(args.deployment, args.output_format)
            logger.info("Deployment bundle created successfully with %d deployment(s).", len(args.deployment))
            write_binary_result(bundle, output_path)

        else:
            validator = DeploymentConfigurationValidator(repository, resolver)
            if args.deployment:
                logger.info("Validating configuration closure for deployment '%s'.", args.deployment)
                result = validator.validate_deployment(args.deployment)
            else:
                logger.info("Validating complete configuration root '%s'.", repository.config_root)
                result = validator.validate_all()
            logger.info("Configuration validation completed successfully (%d files).", len(result["validated_files"]))
            write_result(result, args.output_format, output_path, "validation-report")

        return 0
    except OrchestratorError as exc:
        if logger is not None:
            logger.error("%s", exc)
        else:
            sys.stderr.write(f"ERROR {exc}\n")
        return exc.exit_code
    except KeyboardInterrupt:
        if logger is not None:
            logger.error("Interrupted by user.")
        else:
            sys.stderr.write("ERROR Interrupted by user.\n")
        return 130
    except Exception as exc:  # defensive CLI boundary
        if logger is not None:
            logger.error("Unexpected failure: %s", exc)
            logger.debug("Unexpected exception details", exc_info=True)
        else:
            sys.stderr.write(f"ERROR Unexpected failure: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
