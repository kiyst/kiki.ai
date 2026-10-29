from pathlib import Path

from kiki.evals import EvalCase, _looks_like_abstention, run_evaluation
from kiki.retrieval import SearchResult


class FakeSearch:
    def __init__(self, paths: list[str]) -> None:
        self.paths = paths

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        return [
            SearchResult(
                source_id=str(index),
                path=path,
                location_kind="line",
                start_location=1,
                end_location=2,
                excerpt="evidence",
                score=1.0,
            )
            for index, path in enumerate(self.paths[:limit])
        ]


def test_exact_insufficient_evidence_phrase_is_an_abstention() -> None:
    assert _looks_like_abstention("Evidence is insufficient. No supporting passage was found.")


def test_evaluation_reports_lexical_and_hybrid_source_hits(tmp_path: Path) -> None:
    case = EvalCase(
        id="semantic_win",
        prompt="paraphrased question",
        expected_sources=["expected.txt"],
        answerable=True,
        split="development",
    )

    receipt = run_evaluation(
        [case],
        FakeSearch([str(tmp_path / "other.txt")]),
        FakeSearch([str(tmp_path / "expected.txt")]),
    )

    assert receipt["summary"]["lexical_top_k_any_hits"] == 0
    assert receipt["summary"]["hybrid_top_k_any_hits"] == 1
    assert receipt["cases"][0]["hybrid_all_hit"] is True
