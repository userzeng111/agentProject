from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_EMBEDDING_PROJECT_ROOT = PROJECT_ROOT / "embeddingProject"
DEFAULT_ARTIFACTS_ROOT = PROJECT_ROOT / "Data" / "rag" / "novel_corpus"
DEFAULT_GGUF_PATH = DEFAULT_EMBEDDING_PROJECT_ROOT / "models" / "gguf" / "bge-small-zh-v1.5-q4_k_m.gguf"
DEFAULT_EXAMPLE_ROOT = PROJECT_ROOT / "exampleIndexData"
DEFAULT_ARCHIVE_ROOT = PROJECT_ROOT / "tasklog" / "archive"


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(slots=True)
class RagConfig:
    enabled: bool = True
    embedding_project_root: Path = DEFAULT_EMBEDDING_PROJECT_ROOT
    artifacts_root: Path = DEFAULT_ARTIFACTS_ROOT
    gguf_path: Path = DEFAULT_GGUF_PATH
    example_root: Path = DEFAULT_EXAMPLE_ROOT
    archive_root: Path = DEFAULT_ARCHIVE_ROOT
    runtime: str = "llama.cpp"
    model_name: str = "bge-small-zh-v1.5-q4_k_m"
    namespace: str = "llama_cpp__bge-small-zh-v1.5-q4_k_m"
    n_ctx: int = 512
    n_threads: int | None = None
    n_batch: int = 512
    top_k: int = 3
    score_threshold: float = 0.3
    max_context_chars: int = 3000

    @property
    def faiss_index_path(self) -> Path:
        return self.library_dir / "index.faiss"

    @property
    def sqlite_path(self) -> Path:
        return self.library_dir / "metadata.sqlite3"

    @property
    def library_dir(self) -> Path:
        return self.artifacts_root / self.namespace

    @property
    def status_path(self) -> Path:
        return self.library_dir / "status.json"

    @classmethod
    def from_env(cls) -> "RagConfig":
        return cls(
            enabled=_env_flag("RAG_ENABLED", True),
            embedding_project_root=Path(os.getenv("RAG_EMBEDDING_PROJECT_ROOT", str(DEFAULT_EMBEDDING_PROJECT_ROOT))),
            artifacts_root=Path(os.getenv("RAG_ARTIFACTS_ROOT", str(DEFAULT_ARTIFACTS_ROOT))),
            gguf_path=Path(os.getenv("RAG_GGUF_PATH", str(DEFAULT_GGUF_PATH))),
            example_root=Path(os.getenv("RAG_EXAMPLE_ROOT", str(DEFAULT_EXAMPLE_ROOT))),
            archive_root=Path(os.getenv("RAG_ARCHIVE_ROOT", str(DEFAULT_ARCHIVE_ROOT))),
            runtime=os.getenv("RAG_RUNTIME", "llama.cpp").strip() or "llama.cpp",
            model_name=os.getenv("RAG_MODEL_NAME", "bge-small-zh-v1.5-q4_k_m").strip() or "bge-small-zh-v1.5-q4_k_m",
            namespace=os.getenv("RAG_NAMESPACE", "llama_cpp__bge-small-zh-v1.5-q4_k_m").strip() or "llama_cpp__bge-small-zh-v1.5-q4_k_m",
            n_ctx=int(os.getenv("RAG_N_CTX", "512")),
            n_threads=int(os.getenv("RAG_N_THREADS")) if os.getenv("RAG_N_THREADS") else None,
            n_batch=int(os.getenv("RAG_N_BATCH", "512")),
            top_k=int(os.getenv("RAG_TOP_K", "3")),
            score_threshold=float(os.getenv("RAG_SCORE_THRESHOLD", "0.3")),
            max_context_chars=int(os.getenv("RAG_MAX_CONTEXT_CHARS", "3000")),
        )
