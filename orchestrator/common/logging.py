from __future__ import annotations

import logging
from pathlib import Path

from .errors import OutputWriteError

TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def _trace(self: logging.Logger, message, *args, **kwargs):
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)


if not hasattr(logging.Logger, "trace"):
    logging.Logger.trace = _trace  # type: ignore[attr-defined]

LOG_LEVELS = {
    "TRACE": TRACE,
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def configure_processing_logger(level_name: str, processing_file: Path | None) -> logging.Logger:
    logger = logging.getLogger("algites_orchestrator")
    logger.handlers.clear()
    logger.propagate = False
    level = LOG_LEVELS[level_name]
    logger.setLevel(level)
    formatter = logging.Formatter("%(levelname)s %(message)s")

    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(level)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    if processing_file is not None:
        try:
            processing_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(processing_file, mode="w", encoding="utf-8")
        except OSError as exc:
            raise OutputWriteError(
                f"Cannot open processing info file '{processing_file}': {exc}"
            ) from exc
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
