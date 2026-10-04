import unittest
from dataclasses import replace

from _helpers import WhitespaceTokenizer

from pasr.candidates import (
    CandidateSpan,
    duplicate_span_ratio,
    fuse_candidates,
    generate_lexical_candidates,
    rank_candidates,
    semantic_candidates_from_spans,
)


class CandidateGenerationTests(unittest.TestCase):
    def test_lexical_candidates_return_original_raw_token_blocks(self):
        tokens = "noise one target alpha filler target alpha beta tail".split()
        tokenizer = WhitespaceTokenizer(tokens)

        candidates = generate_lexical_candidates(
            text=" ".join(tokens),
            query="target alpha beta",
            tokenizer=tokenizer,
            source="sample.txt",
            block_size=4,
        )

        self.assertEqual(candidates[0].start, 4)
        self.assertEqual(candidates[0].end, 8)
        self.assertEqual(candidates[0].text, "filler target alpha beta")
        self.assertEqual(candidates[0].selection_reasons, ("lexical_anchor",))
        self.assertEqual(candidates[0].score_components["lexical_match_count"], 3.0)

    def test_semantic_adapter_uses_shared_candidate_contract(self):
        candidates = semantic_candidates_from_spans(
            [
                {
                    "block_idx": 2,
                    "abs_start": 8,
                    "abs_end": 12,
                    "token_count": 4,
                    "score": 0.4,
                    "text": "raw semantic block",
                }
            ],
            source="source.md",
        )

        self.assertEqual(candidates[0].key, ("source.md", 8, 12))
        self.assertEqual(candidates[0].score_components, {"semantic": 0.4})
        self.assertEqual(candidates[0].to_dict(1)["selection_rank"], 1)

    def test_rrf_fuses_duplicate_raw_spans_and_preserves_reasons(self):
        semantic = CandidateSpan(
            source="source.md",
            start=0,
            end=4,
            token_count=4,
            text="shared raw text",
            selection_reasons=("semantic_embedding",),
            score_components={"semantic": 0.8},
            rank_score=0.8,
        )
        lexical = CandidateSpan(
            source="source.md",
            start=0,
            end=4,
            token_count=4,
            text="shared raw text",
            selection_reasons=("lexical_anchor",),
            score_components={"lexical_coverage": 1.0},
            rank_score=1.0,
        )

        fused = fuse_candidates({"semantic": [semantic], "lexical": [lexical]}, rrf_k=60)

        self.assertEqual(len(fused), 1)
        self.assertEqual(
            fused[0].selection_reasons,
            ("lexical_anchor", "semantic_embedding"),
        )
        self.assertAlmostEqual(fused[0].score_components["rrf"], 2 / 61)
        self.assertEqual(duplicate_span_ratio({"semantic": [semantic], "lexical": [lexical]}), 0.5)

    def test_repeated_span_within_one_signal_cannot_inflate_rrf_votes(self):
        first = CandidateSpan("a.md", 0, 2, 2, "alpha", ("lexical_anchor",), {}, 2.0)
        second = CandidateSpan("b.md", 0, 2, 2, "beta", ("lexical_anchor",), {}, 1.0)
        semantic = replace(second, selection_reasons=("semantic_embedding",))
        baseline = fuse_candidates({"lexical": [first, second], "semantic": [semantic]})
        repeated = fuse_candidates({"lexical": [first, first, second], "semantic": [semantic]})

        self.assertEqual(
            [(candidate.key, candidate.rank_score) for candidate in repeated],
            [(candidate.key, candidate.rank_score) for candidate in baseline],
        )
        self.assertEqual(repeated[0].source, "b.md")

    def test_exact_span_fusion_preserves_dependency_ordering_metadata(self):
        from pasr.packing import pack_score_only

        caller = CandidateSpan(
            "source.py",
            0,
            4,
            4,
            "def caller(): return helper()",
            ("bm25",),
            {},
            2.0,
            metadata={"provenance": "source.py:1"},
        )
        helper = CandidateSpan(
            "source.py",
            4,
            8,
            4,
            "def helper(): return 1",
            ("bm25",),
            {},
            1.0,
            metadata={"provenance": "source.py:2"},
        )
        structural = [
            replace(
                caller, selection_reasons=("symbol",), metadata={"symbols": ["caller"], "dependencies": ["helper"]}
            ),
            replace(helper, selection_reasons=("symbol",), metadata={"symbols": ["helper"], "dependencies": []}),
        ]
        fused = fuse_candidates({"bm25": [caller, helper], "symbols": structural})
        result = pack_score_only(fused, "caller helper", budget_tokens=8)

        self.assertEqual([candidate.start for candidate in result.selected], [4, 0])
        self.assertEqual(
            [candidate.metadata["provenance"] for candidate in result.selected],
            ["source.py:2", "source.py:1"],
        )

    def test_ranking_is_stable_and_top_k_is_validated(self):
        first = CandidateSpan("b.md", 0, 2, 2, "b", ("lexical_anchor",), {}, 1.0)
        second = CandidateSpan("a.md", 2, 4, 2, "a", ("lexical_anchor",), {}, 1.0)

        self.assertEqual(rank_candidates([first, second], top_k=1)[0].source, "a.md")
        with self.assertRaisesRegex(ValueError, "top_k"):
            rank_candidates([first], top_k=0)


if __name__ == "__main__":
    unittest.main()
