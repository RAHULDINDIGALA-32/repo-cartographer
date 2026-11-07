from types import SimpleNamespace

import pytest

from app.config.pipeline import PipelineConfig
from app.evaluation import retrieval_metrics, validate_questions
from app.generation.citations import validate_citations
from app.models import ChunkRecord, ContextBlock, QueryAnalysis, RetrievalHit
from app.retrieval.analyzers import RuleAnalyzer, parse_analysis_json
from app.retrieval.hybrid import HybridRetriever, WeightedRRF
from app.retrieval.priors import apply_priors


def hit(chunk_id, path="src/a.py", symbol="foo", score=1.0, rank=1, symbol_type="function"):
    chunk = ChunkRecord(
        id=chunk_id,
        file_id=chunk_id,
        repo_id=1,
        path=path,
        symbol=symbol,
        symbol_type=symbol_type,
        start_line=chunk_id,
        end_line=chunk_id + 1,
        text=f"def {symbol}(): return {chunk_id}",
        token_count=5,
        chunker_version="x",
        content_hash="h",
        search_text=symbol,
    )
    return RetrievalHit(chunk=chunk, score=score, rank=rank, source="dense")


@pytest.mark.asyncio
async def test_rule_analyzer_extracts_identifiers_keywords_and_test_intent():
    result = await RuleAnalyzer().analyze("How does `wsgi_app()` call RequestContext in tests?")
    assert "wsgi_app" in result.identifiers
    assert "RequestContext" in result.identifiers
    assert "route" not in result.keywords
    assert result.wants_tests is True
    assert result.source == "rule"


def test_llm_analysis_parser_rejects_hostile_paths_and_accepts_wrapped_json():
    result = parse_analysis_json(
        'prefix {"identifiers":["pop"],"path_hints":["../../etc"],"keywords":["mint"]} suffix', "q"
    )
    assert result is not None
    assert result.identifiers == ["pop"]
    assert result.path_hints == []


def test_weighted_rrf_deduplicates_and_keeps_trace():
    config = PipelineConfig()
    fuser = WeightedRRF(config=config)
    result = fuser.fuse(
        [[hit(1), hit(2, score=0.5)], [hit(2), hit(3)]], 3, [2, 1], ["dense", "sparse"]
    )
    assert [item.chunk.id for item in result] == [2, 1, 3]
    assert fuser.last_trace["items"][0]["per_list_ranks"] == {"dense": 2, "sparse": 1}


def test_priors_apply_test_penalty_and_path_boost():
    config = PipelineConfig(
        priors={"test_multiplier": 0.5, "header_multiplier": 0.5, "path_hint_multiplier": 2.0}
    )
    analysis = QueryAnalysis(original_query="q", rewritten_query="q", path_hints=["src"])
    values, applied = apply_priors(
        [hit(1, "tests/test_a.py"), hit(2, "src/a.py")], analysis, config
    )
    assert values[0].score == 2.0
    assert {item["id"] for item in applied} == {1, 2}


def test_citation_variants_are_normalized_and_metrics_are_counted():
    blocks = [
        ContextBlock(index=i, chunk_id=i, path="src/a.py", start_line=i, end_line=i + 1, text="x")
        for i in range(1, 9)
    ]
    result = validate_citations("answer 【5】 【1†L1-L2】 [4]–[7] [2, 3]", blocks, "o", "r", "sha")
    assert result.used == list(range(1, 8))
    assert "fullwidth" in result.variants_normalized
    assert retrieval_metrics([hit(1)], [{"path": "src/a.py", "lines": [1, 2]}])["hit@1"] == 1


def test_eval_validator_requires_gold_for_answerable():
    result = validate_questions(
        [
            {
                "id": "q1",
                "repo": "r",
                "question": "q",
                "category": "locate",
                "split": "tune",
                "answerable": True,
                "gold": [],
            }
        ]
    )
    assert result["ok"] is False


def test_rule_analyzer_can_be_built_by_injected_pipeline():
    assert RuleAnalyzer(config=object(), db=object()).name == "rule"


def test_hybrid_retriever_exposes_b4_index_metadata_contract():
    config = PipelineConfig(retriever="hybrid")
    retriever = HybridRetriever(
        config=config, db=object(), settings=SimpleNamespace(db_schema="cartographer")
    )
    assert retriever.last_indexed_sha is None
    assert retriever.last_status is None
