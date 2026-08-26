from __future__ import annotations


class OrchestratorError(Exception):
    """Base error carrying the stable CLI exit code."""

    exit_code = 1


class CliArgumentError(OrchestratorError):
    exit_code = 2


class ConfigurationValidationError(OrchestratorError):
    exit_code = 3


class UnresolvedReferenceError(OrchestratorError):
    exit_code = 4


class AmbiguousReferenceError(OrchestratorError):
    exit_code = 5


class OutputWriteError(OrchestratorError):
    exit_code = 6


class ResolutionError(OrchestratorError):
    exit_code = 7
