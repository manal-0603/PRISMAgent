"""Hybrid RAG index over the review corpus.

Pipeline for every query:

    dense retrieval (Chroma, sentence embeddings)  ─┐
                                                    ├─ reciprocal rank fusion ─ cross-encoder
    sparse retrieval (BM25)                        ─┘   re-ranking ─ contextual compression

* Dense catches paraphrases, sparse catches exact terms (drug names, acronyms, numbers).
* Re-ranking (FlashRank cross-encoder) reorders the fused candidates by true relevance.
* Compression keeps only the sentences most related to the query so that the
  evidence fits in a small prompt. Sentences are kept verbatim, which is what lets
  the pipeline verify that every quoted passage really exists in the source.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import Settings


@dataclass
class Chunk:
    id: str  # "<rid>:<kind>:<n>"
    rid: str
    kind: str  # "abstract" | "fulltext"
    text: str
    score: float = 0.0
    section: str = ""  # heading of the section the chunk comes from, when known


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) > 2]


class FastEmbedEmbeddings(Embeddings):
    """Local ONNX sentence embeddings (no server, no API key)."""

    def __init__(self, model_name: str, cache_dir: Path):
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir / "fastembed"))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts, batch_size=32)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.query_embed(text))).tolist()


def make_embeddings(settings: Settings) -> Embeddings:
    if settings.embedding_provider == "ollama":
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(model=settings.ollama_embedding_model, base_url=settings.ollama_base_url)
    return FastEmbedEmbeddings(settings.embedding_model, settings.cache_dir)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class HybridIndex:
    def __init__(self, persist_dir: Path, settings: Settings):
        from langchain_chroma import Chroma

        self.settings = settings
        self.dir = persist_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.embeddings = make_embeddings(settings)
        self.vectors = Chroma(
            collection_name="review_corpus",
            embedding_function=self.embeddings,
            persist_directory=str(self.dir),
            collection_metadata={"hnsw:space": "cosine"},
        )
        self._chunk_file = self.dir / "chunks.jsonl"
        self.chunks: dict[str, Chunk] = {}
        if self._chunk_file.exists():
            for line in self._chunk_file.open(encoding="utf-8"):
                chunk = Chunk(**json.loads(line))
                self.chunks[chunk.id] = chunk
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            separators=["\n## ", "\n\n", "\n", ". ", " "],
        )
        self._bm25_cache: dict[tuple, tuple] = {}
        self._ranker = None

    # -- construction ------------------------------------------------------- #
    def has(self, rid: str, kind: str) -> bool:
        return f"{rid}:{kind}:0" in self.chunks

    def add(self, rid: str, text: str, kind: str, title: str = "") -> int:
        """Chunk, embed and store one document. Returns the number of chunks."""
        return self.add_many([(rid, text, kind, title)])

    def add_many(self, documents: list[tuple[str, str, str, str]], batch_size: int = 64) -> int:
        """Index several (rid, text, kind, title) documents. Already-indexed ones are skipped."""
        new: list[Chunk] = []
        embed_texts: list[str] = []
        for rid, text, kind, title in documents:
            if not text.strip() or self.has(rid, kind):
                continue
            pieces = [text] if kind == "abstract" else self._splitter.split_text(text)
            section = ""
            for i, piece in enumerate(p.strip() for p in pieces if p.strip()):
                headings = re.findall(r"^## (.+)$", piece, flags=re.M)
                # a chunk that opens with a heading belongs to it; otherwise to the section in progress
                own = headings[0] if headings and piece.startswith("## ") else section
                new.append(Chunk(id=f"{rid}:{kind}:{i}", rid=rid, kind=kind, text=piece, section=own[:80]))
                if headings:
                    section = headings[-1]
                # abstracts are embedded with their title, full-text chunks with their section name
                if kind == "abstract":
                    embed_texts.append(f"{title}. {piece}" if title else piece)
                else:
                    embed_texts.append(f"{own}: {piece}" if own and not piece.startswith("## ") else piece)
        for start in range(0, len(new), batch_size):
            batch = new[start : start + batch_size]
            self.vectors.add_texts(
                texts=embed_texts[start : start + batch_size],
                metadatas=[{"rid": c.rid, "kind": c.kind} for c in batch],
                ids=[c.id for c in batch],
            )
            with self._chunk_file.open("a", encoding="utf-8") as fh:
                for chunk in batch:
                    self.chunks[chunk.id] = chunk
                    fh.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
        if new:
            self._bm25_cache.clear()
        return len(new)

    # -- retrieval ---------------------------------------------------------- #
    def _candidates(self, rids: list[str] | None, kind: str | None) -> list[Chunk]:
        wanted = set(rids) if rids else None
        return [
            c for c in self.chunks.values()
            if (wanted is None or c.rid in wanted) and (kind is None or c.kind == kind)
        ]

    def _sparse(self, query: str, pool: list[Chunk], key: tuple, top: int) -> list[str]:
        from rank_bm25 import BM25Okapi

        if not pool:
            return []
        if key not in self._bm25_cache:
            corpus = [tokenize(f"{c.section} {c.text}") or ["_"] for c in pool]
            self._bm25_cache[key] = (BM25Okapi(corpus), [c.id for c in pool])
        bm25, ids = self._bm25_cache[key]
        scores = bm25.get_scores(tokenize(query))
        ranked = sorted(zip(ids, scores), key=lambda pair: pair[1], reverse=True)
        return [cid for cid, score in ranked[:top] if score > 0]

    def _dense(self, query: str, rids: list[str] | None, kind: str | None, top: int) -> list[str]:
        clauses = []
        if rids:
            clauses.append({"rid": rids[0]} if len(rids) == 1 else {"rid": {"$in": list(rids)}})
        if kind:
            clauses.append({"kind": kind})
        where = None if not clauses else clauses[0] if len(clauses) == 1 else {"$and": clauses}
        hits = self.vectors.similarity_search(query, k=top, filter=where)
        return [doc.id for doc in hits if doc.id]

    def _rerank(self, query: str, chunks: list[Chunk]) -> list[Chunk]:
        from flashrank import Ranker, RerankRequest

        if self._ranker is None:
            self._ranker = Ranker(
                model_name=self.settings.reranker_model, cache_dir=str(self.settings.cache_dir / "flashrank")
            )
        passages = [{"id": c.id, "text": f"{c.section}: {c.text}" if c.section else c.text} for c in chunks]
        ranked = self._ranker.rerank(RerankRequest(query=query, passages=passages))
        by_id = {c.id: c for c in chunks}
        return [replace(by_id[item["id"]], score=float(item["score"])) for item in ranked]

    def search(
        self,
        query: str,
        k: int = 6,
        rids: list[str] | None = None,
        kind: str | None = None,
        fetch_k: int = 24,
        rerank: bool = True,
    ) -> list[Chunk]:
        """Hybrid search. `rids` restricts the search to some records, `kind` to abstracts or full texts."""
        pool = self._candidates(rids, kind)
        if not pool:
            return []
        key = (tuple(sorted(rids)) if rids else None, kind)
        sparse = self._sparse(query, pool, key, fetch_k)
        dense = self._dense(query, rids, kind, fetch_k)
        fused: dict[str, float] = {}
        for ranking in (dense, sparse):
            for rank, cid in enumerate(ranking):
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (60 + rank + 1)  # reciprocal rank fusion
        ordered = sorted(fused, key=fused.get, reverse=True)[:fetch_k]
        chunks = [replace(self.chunks[cid], score=fused[cid]) for cid in ordered if cid in self.chunks]
        if rerank and len(chunks) > 1:
            chunks = self._rerank(query, chunks)
        return chunks[:k]

    def multi_search(self, queries: list[str], per_query: int = 3, max_chunks: int = 10, **kwargs) -> list[Chunk]:
        """Union of the best chunks for several queries (one query per data item / criterion)."""
        best: dict[str, Chunk] = {}
        for query in queries:
            for chunk in self.search(query, k=per_query, **kwargs):
                if chunk.id not in best or chunk.score > best[chunk.id].score:
                    best[chunk.id] = chunk
        ranked = sorted(best.values(), key=lambda c: c.score, reverse=True)[:max_chunks]
        # present passages in document order: easier for the model, and stable
        return sorted(ranked, key=lambda c: (c.rid, c.kind, int(c.id.rsplit(":", 1)[1])))

    # -- contextual compression --------------------------------------------- #
    def compress(self, query: str, chunks: list[Chunk], max_chars: int) -> list[Chunk]:
        """Keep the sentences most similar to the query until the budget is met.

        Chunks that already fit are returned untouched. Sentences stay verbatim and
        in their original order.
        """
        if sum(len(c.text) for c in chunks) <= max_chars:
            return chunks
        sentences = [(ci, si, s) for ci, c in enumerate(chunks) for si, s in enumerate(split_sentences(c.text))]
        if not sentences:
            return chunks
        q_vec = self.embeddings.embed_query(query)
        s_vecs = self.embeddings.embed_documents([s for _, _, s in sentences])
        scored = sorted(zip(sentences, (_cosine(q_vec, v) for v in s_vecs)), key=lambda pair: pair[1], reverse=True)
        keep: set[tuple[int, int]] = set()
        used = 0
        for (ci, si, sentence), _ in scored:
            if used + len(sentence) > max_chars:
                continue
            keep.add((ci, si))
            used += len(sentence) + 1
        out = []
        for ci, chunk in enumerate(chunks):
            kept = [s for cj, si, s in sentences if cj == ci and (ci, si) in keep]
            if kept:
                out.append(replace(chunk, text=" […] ".join(kept)))
        return out


def format_passages(chunks: list[Chunk]) -> str:
    return "\n\n".join(
        f"[{c.id}]" + (f" (section: {c.section})" if c.section else "") + f"\n{c.text}" for c in chunks
    )
