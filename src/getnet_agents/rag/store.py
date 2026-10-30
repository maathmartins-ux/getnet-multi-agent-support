"""Storage + retrieval for the RAG pipeline (FR-003).

- `load_documents(dir)` parses markdown files with a small frontmatter (title,url,lang,keywords).
- `chunk(doc)` splits by `##` headings then packs paragraphs up to ~700 chars.
- `BM25Index` is a pure-Python Okapi BM25 (accent-insensitive, bilingual stopwords). The frontmatter
  keywords are appended to every chunk of the document so English queries match Portuguese chunks.
- `KnowledgeBase.retrieve(query)` returns top-k chunks above a relative score threshold.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

STOPWORDS = set(
    """a o os as um uma uns umas de do da dos das em no na nos nas por para com sem sobre e ou que se
    ao à às é são foi ser ter tem como mais menos muito meu minha seu sua isso esse essa este esta
    the a an of to in on for with and or is are was be my your this that it at by from do does
    i you we they can how what when where which who why will would should could there here""".split()
)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", normalize(text)) if len(t) > 1 and t not in STOPWORDS]


@dataclass
class Document:
    path: str
    title: str
    url: str | None
    lang: str
    keywords: list[str]
    body: str


@dataclass
class Chunk:
    id: str
    doc_title: str
    url: str | None
    heading: str
    text: str
    keywords: list[str] = field(default_factory=list)


@dataclass
class Retrieved:
    chunk: Chunk
    score: float


_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def parse_markdown(path: Path) -> Document:
    raw = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    body = raw
    m = _FRONTMATTER.match(raw)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip().strip('"')
        body = raw[m.end():]
    keywords = [k.strip() for k in meta.get("keywords", "").split(",") if k.strip()]
    title = meta.get("title") or path.stem.replace("-", " ").title()
    return Document(path=str(path), title=title, url=meta.get("url"), lang=meta.get("lang", "pt"),
                    keywords=keywords, body=body.strip())


def load_documents(directory: str | Path) -> list[Document]:
    directory = Path(directory)
    files = sorted(p for p in directory.glob("*.md") if p.name.upper() not in {"SOURCES.MD", "README.MD"})
    return [parse_markdown(p) for p in files]


def chunk_document(doc: Document, *, max_chars: int = 700) -> list[Chunk]:
    chunks: list[Chunk] = []
    heading = doc.title
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            text = "\n".join(buffer).strip()
            if text:
                chunks.append(Chunk(id=f"{Path(doc.path).stem}#{len(chunks)}", doc_title=doc.title, url=doc.url,
                                    heading=heading, text=text, keywords=doc.keywords))
            buffer.clear()

    for block in re.split(r"\n\s*\n", doc.body):
        block = block.strip()
        if not block:
            continue
        if block.startswith("#"):
            flush()
            heading = block.lstrip("#").strip()
            continue
        if sum(len(b) for b in buffer) + len(block) > max_chars:
            flush()
        buffer.append(block)
    flush()
    return chunks


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self._docs: list[list[str]] = []
        self._tf: list[Counter[str]] = []
        self._df: Counter[str] = Counter()
        self._avgdl = 0.0

    def add(self, tokens: list[str]) -> int:
        self._docs.append(tokens)
        tf = Counter(tokens)
        self._tf.append(tf)
        self._df.update(tf.keys())
        self._avgdl = sum(len(d) for d in self._docs) / len(self._docs)
        return len(self._docs) - 1

    def idf(self, term: str) -> float:
        n, df = len(self._docs), self._df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(self, query_tokens: list[str], top_k: int = 5) -> list[tuple[int, float]]:
        scores: dict[int, float] = defaultdict(float)
        for term in set(query_tokens):
            if term not in self._df:
                continue
            idf = self.idf(term)
            for i, tf in enumerate(self._tf):
                f = tf.get(term)
                if not f:
                    continue
                dl = len(self._docs[i])
                denom = f + self.k1 * (1 - self.b + self.b * dl / self._avgdl)
                scores[i] += idf * f * (self.k1 + 1) / denom
        return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]


class KnowledgeBase:
    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents
        self.chunks: list[Chunk] = [c for d in documents for c in chunk_document(d)]
        self.index = BM25Index()
        for c in self.chunks:
            # field weighting: heading x3, document keywords x2 (bilingual), title x2, body x1
            fields = [c.heading] * 3 + [" ".join(c.keywords)] * 2 + [c.doc_title] * 2 + [c.text]
            self.index.add(tokenize(" ".join(fields)))

    @classmethod
    def from_directory(cls, directory: str | Path) -> "KnowledgeBase":
        return cls(load_documents(directory))

    def retrieve(self, query: str, *, top_k: int = 4, relative_threshold: float = 0.35,
                 max_per_doc: int = 2) -> list[Retrieved]:
        """Top-k chunks above a relative threshold, with at most `max_per_doc` chunks per document (diversity)."""
        hits = self.index.search(tokenize(query), top_k=top_k * 3)
        if not hits:
            return []
        best = hits[0][1]
        out: list[Retrieved] = []
        per_doc: dict[str, int] = {}
        for i, s in hits:
            chunk = self.chunks[i]
            if s <= 0 or s < best * relative_threshold:
                break
            if per_doc.get(chunk.doc_title, 0) >= max_per_doc:
                continue
            per_doc[chunk.doc_title] = per_doc.get(chunk.doc_title, 0) + 1
            out.append(Retrieved(chunk=chunk, score=round(s, 3)))
            if len(out) >= top_k:
                break
        return out
