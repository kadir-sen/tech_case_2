from app.rag.retriever import FaqRetriever


def test_retriever_loads_and_searches():
    FaqRetriever.reset()
    r = FaqRetriever.instance()
    ctx = r.search("ikinci el araçta maksimum ne kadar finansman alabilirim", k=3)
    assert ctx.hits, "retriever returned no hits"
    top_text = " ".join(h.document.text.lower() for h in ctx.hits)
    assert "%40" in top_text or "40" in top_text
    assert "3.000.000" in top_text or "3 milyon" in top_text.lower() or "3000000" in top_text


def test_retriever_returns_citations():
    FaqRetriever.reset()
    r = FaqRetriever.instance()
    ctx = r.search("7 milyon üzeri", k=2)
    cites = ctx.citations()
    assert cites
    assert any("vehicle_finance_faq.md" in c for c in cites)


def test_retriever_is_topic_specific():
    FaqRetriever.reset()
    r = FaqRetriever.instance()
    ctx = r.search("kefil ne zaman gerekli", k=3)
    top = ctx.hits[0].document.text.lower()
    assert "kefil" in top
