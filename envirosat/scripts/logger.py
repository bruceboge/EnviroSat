#!/usr/bin/env python3
"""
EnviroSat — scripts/logger.py
JSON Lines data logging to microSD card.

Every sensor reading is appended as a single JSON line to the current
session log file. One record per line — human-readable, directly
importable into Python, Excel, or any data analysis tool.

File naming:
  envirosat_YYYY-MM-DD_HHMMSS.jsonl
  A new file is created each time the system boots. No session ever
  overwrites another. At one record per minute, a 32 GB microSD
  will take decades to fill.

Format example (one line, pretty-printed here for readability):
  {
    "satellite_id": "ES-01",
    "timestamp": "2026-03-05T14:32:01Z",
    "temperature_c": 21.4,
    "pressure_hpa": 1013.2,
    ...
  }

Author:  EnviroSat Team
Licence: MIT
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("logger")

FLUSH_EVERY = 5     # Flush the file buffer after this many records


class DataLogger:
    """
    Append data records as JSON Lines to a session log file.

    Usage:
        logger = DataLogger("/home/envirosat/envirosat/logs")
        logger.write(record_dict)
        logger.close()
    """

    def __init__(self, log_dir: str):
        self._log_dir  = log_dir
        self._lock     = threading.Lock()
        self._file     = None
        self._count    = 0
        self._filepath = None
        self._open_file()

    def _open_file(self):
        """Create the log directory and open a new session file."""
        Path(self._log_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        filename      = f"envirosat_{ts}.jsonl"
        self._filepath = os.path.join(self._log_dir, filename)
        try:
            self._file = open(self._filepath, "a", encoding="utf-8", buffering=1)
            log.info(f"Log file opened: {self._filepath}")
        except OSError as exc:
            log.error(f"Cannot open log file {self._filepath}: {exc}")
            self._file = None

    def write(self, record: dict):
        """
        Append one record as a JSON line. Thread-safe.
        Raises nothing — logs errors internally to avoid crashing the main loop.
        """
        if self._file is None:
            log.error("Logger has no open file — record dropped.")
            return

        try:
            line = json.dumps(record, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            log.error(f"JSON serialisation failed: {exc}")
            return

        with self._lock:
            try:
                self._file.write(line + "\n")
                self._count += 1
                if self._count % FLUSH_EVERY == 0:
                    self._file.flush()
                    os.fsync(self._file.fileno())
            except OSError as exc:
                log.error(f"Log write failed: {exc}")

    def close(self):
        """Flush and close the log file cleanly."""
        with self._lock:
            if self._file:
                try:
                    self._file.flush()
                    os.fsync(self._file.fileno())
                    self._file.close()
                    log.info(f"Log file closed: {self._filepath} ({self._count} records written)")
                except OSError as exc:
                    log.warning(f"Error closing log file: {exc}")
                finally:
                    self._file = None

    @property
    def filepath(self) -> str:
        """Return the path of the current log file."""
        return self._filepath

    @property
    def record_count(self) -> int:
        """Return the number of records written this session."""
        with self._lock:
            return self._count

    def tail(self, n: int = 10) -> list:
        """
        Return the last n records from the current log file as dicts.
        Useful for health checks — does not block the write path.
        """
        if not self._filepath or not os.path.exists(self._filepath):
            return []
        try:
            with open(self._filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            records = []
            for line in lines[-n:]:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            return records
        except OSError:
            return []
