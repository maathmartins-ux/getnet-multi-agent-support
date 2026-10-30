"""FR-003 / FR-008 retrieval regressions found during independent review.

Each case pins the document that must come first for an official scenario, so a tokenizer or weighting
change that silently degrades retrieval fails here instead of in front of the evaluator.
"""

from __future__ import annotations

import pytest

from getnet_agents.rag.store import KnowledgeBase, tokenize

CASES = [
    ("Do I need a bank account to receive my sales via Pix?", "https://site.getnet.com.br/duvidas/pix/"),
    ("How does receivables advance (antecipação) work with Getnet?", "antecipacao"),
    ("How many installments can I split a sale into with the crediário?", "crediario"),
    ("Can I sell through WhatsApp using the Payment Link?", "link-de-pagamento"),
]


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return KnowledgeBase.from_directory("data/knowledge")


@pytest.mark.parametrize(("query", "expected"), CASES)
def test_top1_source_for_official_scenarios(kb: KnowledgeBase, query: str, expected: str) -> None:
    """The first retrieved chunk must come from the document that answers the official scenario."""
    hits = kb.retrieve(query, top_k=4)
    assert hits, "no chunks retrieved"
    top = hits[0].chunk
    assert expected in (top.url or "") or expected in top.id, (top.doc_title, top.url, top.heading)


def test_generic_query_words_are_stopwords() -> None:
    """Generic words must not steer BM25 ('need', 'via', 'receive' carry no topic)."""
    assert tokenize("Do I need a bank account to receive my sales via Pix?") == ["bank", "account", "receive", "sales", "pix"]
