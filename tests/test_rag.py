"""RAG pipeline (FR-003): ingestion, chunking, BM25 retrieval over the Getnet corpus."""

from __future__ import annotations

from pathlib import Path

from getnet_agents.rag.store import Document, KnowledgeBase, chunk_document, load_documents, parse_markdown, tokenize


def test_tokenize_strips_accents_and_stopwords():
    """FR-003: tokens are accent-insensitive and bilingual stopwords are dropped."""
    assert tokenize("Antecipação de Recebíveis") == ["antecipacao", "recebiveis"]
    assert "the" not in tokenize("What is the Get Smart")
    assert tokenize("a o de") == []


def test_parse_markdown_reads_frontmatter(tmp_path: Path):
    """FR-003: frontmatter (title, url, lang, keywords) is parsed and removed from the body."""
    p = tmp_path / "doc.md"
    p.write_text('---\ntitle: "Teste Doc"\nurl: https://example.com/x\nlang: pt\nkeywords: pix, qr code\n---\n'
                 "## Seção\n\nCorpo do texto.\n", encoding="utf-8")
    doc = parse_markdown(p)
    assert doc.title == "Teste Doc"
    assert doc.url == "https://example.com/x"
    assert doc.lang == "pt"
    assert doc.keywords == ["pix", "qr code"]
    assert doc.body.startswith("## Seção")
    assert "---" not in doc.body


def test_parse_markdown_without_frontmatter_uses_filename(tmp_path: Path):
    """FR-003: a file without frontmatter still becomes a document titled after the file name."""
    p = tmp_path / "get-classica.md"
    p.write_text("Texto simples.", encoding="utf-8")
    doc = parse_markdown(p)
    assert doc.title == "Get Classica"
    assert doc.url is None and doc.keywords == []


def test_chunk_document_respects_max_chars_and_headings():
    """FR-003: chunks are split on `##` headings and packed up to max_chars."""
    paragraphs = "\n\n".join(f"Parágrafo {i} " + ("x" * 40) for i in range(12))
    body = f"## Primeira\n\n{paragraphs}\n\n## Segunda\n\nOutro bloco."
    doc = Document(path="fake/doc.md", title="Doc", url=None, lang="pt", keywords=["k"], body=body)
    chunks = chunk_document(doc, max_chars=120)
    assert len(chunks) > 2
    for c in chunks:
        # "\n".join adds one separator per extra block; the packed payload itself stays within max_chars
        assert len(c.text) <= 120 + c.text.count("\n")
        assert c.keywords == ["k"] and c.doc_title == "Doc"
    assert chunks[0].heading == "Primeira"
    assert chunks[-1].heading == "Segunda" and chunks[-1].text == "Outro bloco."
    assert len({c.id for c in chunks}) == len(chunks)


def test_load_documents_skips_sources_file(settings):
    """FR-003: SOURCES.md is a provenance file, not knowledge; it must not be ingested."""
    from getnet_agents.api import resolve

    docs = load_documents(resolve(settings.knowledge_dir))
    assert all(not Path(d.path).name.upper().startswith("SOURCES") for d in docs)
    assert len(docs) >= 10


def test_knowledge_base_size(orchestrator):
    """FR-003: the corpus ingested from getnet.net has >= 10 documents and > 50 chunks."""
    kb: KnowledgeBase = orchestrator.kb
    assert len(kb.documents) >= 10
    assert len(kb.chunks) > 50
    assert all(d.url for d in kb.documents), "every document should cite its getnet.net source url"


def test_retrieve_get_smart(orchestrator):
    """FR-003: an English query about the Get Smart retrieves the Get Smart chunk."""
    hits = orchestrator.kb.retrieve("Get Smart Android touchscreen")
    assert hits
    assert any("get smart" in (h.chunk.doc_title + " " + h.chunk.text).lower() for h in hits)
    assert hits == sorted(hits, key=lambda h: h.score, reverse=True)
    assert all(h.score > 0 for h in hits)


def test_retrieve_unknown_terms_returns_empty(orchestrator):
    """FR-003 / BR-003: nonsense queries retrieve nothing, which triggers the handoff path."""
    assert orchestrator.kb.retrieve("xyzzy plugh") == []


def test_retrieve_respects_top_k_and_threshold(orchestrator):
    """FR-003: top_k bounds the result size and the relative threshold drops weak hits."""
    hits = orchestrator.kb.retrieve("Pix", top_k=2)
    assert 1 <= len(hits) <= 2
    best = hits[0].score
    assert all(h.score >= best * 0.35 for h in hits)


def test_retrieve_is_accent_insensitive(orchestrator):
    """FR-003: queries with and without accents retrieve the same top document."""
    a = orchestrator.kb.retrieve("antecipação de recebíveis")
    b = orchestrator.kb.retrieve("antecipacao de recebiveis")
    assert a and b
    assert a[0].chunk.doc_title == b[0].chunk.doc_title
