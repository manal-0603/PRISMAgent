"""Per-run context: everything an agent needs besides the (small) graph state.

The LangGraph state only carries identifiers and counters; bulky data lives on
disk in the run directory. Agents obtain the context from the run id, so a run
can be resumed in a new process at any time.
"""

from __future__ import annotations

import json
import platform
import re
import threading
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .audit import ArtifactStore, AuditLog, Timer
from .config import Settings, get_settings
from .llm import LLM


class RunOptions(BaseModel):
    """Knobs of one review run (saved in manifest.json)."""

    max_per_source: int = 60  # records fetched per database (most relevant first)
    max_screen: int = 50  # cap on records sent to LLM screening (relevance-ranked)
    screen_batch_size: int = 6  # records per title/abstract screening call
    fulltext_fallback: str = "abstract"  # "abstract": assess on abstract if no open full text; "exclude"
    max_fulltext_chars: int = 3600  # evidence budget per full-text screening prompt
    max_extraction_chars: int = 6000  # evidence budget per extraction prompt
    max_appraisal_chars: int = 4200  # evidence budget per risk-of-bias prompt
    qa_max_rounds: int = 2  # critic -> writer revision rounds
    exclusion_audit_sample: int = 10  # excluded records re-checked by the critic
    auto_approve: bool = False  # skip human checkpoints (logged as such)
    databases: list[str] | None = None  # override the databases chosen in the protocol
    protocol_template: str = "config/protocol_template.yaml"
    seed: int = 13


def new_run_id(question: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:40].strip("-")
    return f"{datetime.now():%Y%m%d-%H%M%S}-{slug}"


def _versions() -> dict[str, str]:
    out = {"python": platform.python_version()}
    for package in ("langchain-core", "langgraph", "langchain-groq", "chromadb", "fastembed", "flashrank", "rank-bm25"):
        try:
            out[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            out[package] = "not installed"
    return out


class RunContext:
    def __init__(self, run_id: str, settings: Settings | None = None):
        self.run_id = run_id
        self.settings = settings or get_settings()
        self.run_dir: Path = self.settings.runs_dir / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.audit = AuditLog(self.run_dir)
        self.store = ArtifactStore(self.run_dir, self.audit)
        self.timer = Timer(self.store)
        self.llm = LLM(self.settings, self.audit, trace_file=self.run_dir / "llm_trace.jsonl")
        self._index = None
        self._index_lock = threading.Lock()

    # -- manifest ----------------------------------------------------------- #
    @property
    def manifest_path(self) -> Path:
        return self.run_dir / "manifest.json"

    def init_manifest(self, question: str, options: RunOptions) -> None:
        s = self.settings
        manifest = {
            "run_id": self.run_id,
            "question": question,
            "created": datetime.now().isoformat(timespec="seconds"),
            "options": options.model_dump(),
            "llm": {
                "provider": s.llm_provider,
                "primary": s.model_primary,
                "secondary": s.model_secondary,
                "fast": s.model_fast,
                "temperature": 0.0,
                "task_models": s.task_models(),
            },
            "rag": {
                "embedding_provider": s.embedding_provider,
                "embedding_model": s.embedding_model if s.embedding_provider == "fastembed" else s.ollama_embedding_model,
                "reranker": s.reranker_model,
                "chunk_size": s.chunk_size,
                "chunk_overlap": s.chunk_overlap,
            },
            "versions": _versions(),
        }
        self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        self.audit.log("system", "run_created", question=question, options=options.model_dump())

    @property
    def manifest(self) -> dict[str, Any]:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    @property
    def options(self) -> RunOptions:
        return RunOptions.model_validate(self.manifest["options"])

    @property
    def question(self) -> str:
        return self.manifest["question"]

    # -- RAG index (heavy: built lazily, shared) ---------------------------- #
    @property
    def index(self):
        with self._index_lock:
            if self._index is None:
                from .rag.index import HybridIndex

                self._index = HybridIndex(self.run_dir / "chroma", self.settings)
            return self._index


_contexts: dict[str, RunContext] = {}
_lock = threading.Lock()


def get_context(run_id: str) -> RunContext:
    with _lock:
        if run_id not in _contexts:
            _contexts[run_id] = RunContext(run_id)
        return _contexts[run_id]
