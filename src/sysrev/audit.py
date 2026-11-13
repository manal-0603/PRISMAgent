"""Append-only audit trail and versioned artifact store for one review run.

Layout of a run directory::

    runs/<run_id>/
        manifest.json            configuration, model names, package versions
        audit.jsonl              one JSON line per agent action / LLM call / human decision
        protocol_v1.json …       every saved artifact is versioned, never overwritten
        records_raw.jsonl …

Nothing in here talks to an LLM: it is the ground truth the report is built from.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class AuditLog:
    def __init__(self, run_dir: Path):
        self.path = run_dir / "audit.jsonl"
        self._lock = threading.Lock()
        self._seq = sum(1 for _ in self.path.open()) if self.path.exists() else 0

    def log(self, agent: str, action: str, **payload: Any) -> None:
        with self._lock:
            self._seq += 1
            entry = {"seq": self._seq, "ts": _now(), "agent": agent, "action": action, **payload}
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.open(encoding="utf-8") if line.strip()]


class ArtifactStore:
    """Reads and writes run artifacts. JSON artifacts are versioned (name_vN.json)."""

    def __init__(self, run_dir: Path, audit: AuditLog):
        self.dir = run_dir
        self.audit = audit
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- versioned single objects ------------------------------------------ #
    def _versions(self, name: str) -> list[Path]:
        files = self.dir.glob(f"{name}_v*.json")
        return sorted(files, key=lambda p: int(p.stem.rsplit("_v", 1)[1]))

    def save(self, name: str, obj: BaseModel | dict | list, agent: str = "system", note: str = "") -> Path:
        version = len(self._versions(name)) + 1
        path = self.dir / f"{name}_v{version}.json"
        data = obj.model_dump() if isinstance(obj, BaseModel) else obj
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        self.audit.log(agent, "artifact_saved", artifact=name, version=version, file=path.name, note=note)
        return path

    def load(self, name: str, model: type[T] | None = None, version: int | None = None) -> Any:
        versions = self._versions(name)
        if not versions:
            raise FileNotFoundError(f"No artifact '{name}' in {self.dir}")
        path = versions[-1] if version is None else self.dir / f"{name}_v{version}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return model.model_validate(data) if model else data

    def exists(self, name: str) -> bool:
        return bool(self._versions(name)) or (self.dir / f"{name}.jsonl").exists()

    def version_count(self, name: str) -> int:
        return len(self._versions(name))

    # -- record-per-line collections --------------------------------------- #
    def save_lines(self, name: str, items: Iterable[BaseModel | dict], agent: str = "system") -> Path:
        path = self.dir / f"{name}.jsonl"
        count = 0
        with path.open("w", encoding="utf-8") as fh:
            for item in items:
                data = item.model_dump() if isinstance(item, BaseModel) else item
                fh.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
                count += 1
        self.audit.log(agent, "artifact_saved", artifact=name, file=path.name, n=count)
        return path

    def load_lines(self, name: str, model: type[T] | None = None) -> list[Any]:
        path = self.dir / f"{name}.jsonl"
        if not path.exists():
            return []
        rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
        return [model.model_validate(r) for r in rows] if model else rows

    # -- free-form files ---------------------------------------------------- #
    def write_text(self, filename: str, text: str, agent: str = "system") -> Path:
        path = self.dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.audit.log(agent, "file_written", file=filename, chars=len(text))
        return path

    def path(self, filename: str) -> Path:
        return self.dir / filename


class Timer:
    """Records wall-clock seconds spent in each pipeline stage."""

    def __init__(self, store: ArtifactStore):
        self.store = store
        self.file = store.dir / "timings.json"

    def read(self) -> dict[str, float]:
        return json.loads(self.file.read_text()) if self.file.exists() else {}

    def add(self, stage: str, seconds: float) -> None:
        data = self.read()
        data[stage] = round(data.get(stage, 0.0) + seconds, 2)
        self.file.write_text(json.dumps(data, indent=2))

    def stage(self, name: str) -> _StageTimer:
        return _StageTimer(self, name)


class _StageTimer:
    def __init__(self, timer: Timer, name: str):
        self.timer, self.name = timer, name

    def __enter__(self) -> _StageTimer:
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.timer.add(self.name, time.perf_counter() - self.t0)
