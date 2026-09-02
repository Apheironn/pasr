import unittest

from pasr.evidence import account_query_evidence, build_evidence_span, extract_keywords


class EvidenceAccountingTests(unittest.TestCase):
    def test_builds_typed_raw_span_with_stable_identifier(self):
        span = build_evidence_span(
            {
                "source": "src/example.py",
                "abs_start": 10,
                "abs_end": 14,
                "token_count": 4,
                "score": 0.75,
                "text": "def select_context spans",
            }
        )

        self.assertEqual(span.span_id, "src/example.py#tokens=10:14")
        self.assertEqual(span.selection_reasons, ("semantic_embedding",))
        self.assertEqual(span.score_components, {"semantic": 0.75})
        self.assertEqual(span.to_dict()["selection_reasons"], ["semantic_embedding"])

    def test_maps_claim_keywords_to_supporting_spans(self):
        spans = [
            build_evidence_span(
                {
                    "source": "docs/architecture.md",
                    "start": 3,
                    "end": 8,
                    "token_count": 5,
                    "text": "Raw spans preserve source provenance.",
                }
            ),
            build_evidence_span(
                {
                    "source": "docs/evaluation_plan.md",
                    "start": 20,
                    "end": 24,
                    "token_count": 4,
                    "text": "Budget metrics count selected tokens.",
                }
            ),
        ]

        result = account_query_evidence(
            "Preserve raw source spans. Verify missing claims.",
            spans,
            {"final_context_tokens": 30},
        )

        self.assertEqual(result["schema_version"], "1.0")
        self.assertEqual(result["claims"][0]["status"], "supported")
        self.assertEqual(result["claims"][1]["status"], "unsupported")
        self.assertEqual(
            result["claims"][0]["support"][0]["span_id"],
            "docs/architecture.md#tokens=3:8",
        )
        self.assertEqual(result["summary"]["supported_claim_count"], 1)
        self.assertEqual(result["summary"]["unsupported_claim_count"], 1)
        self.assertEqual(result["summary"]["evidence_source_count"], 2)
        self.assertEqual(result["budget"]["selected_raw_span_tokens"], 9)
        self.assertEqual(result["budget"]["final_context_tokens"], 30)

    def test_reports_partial_and_non_evaluable_claims(self):
        span = build_evidence_span(
            {
                "source": "README.md",
                "start": 0,
                "end": 2,
                "text": "context selection",
            }
        )

        result = account_query_evidence("context verification; how is it", [span])

        self.assertEqual(result["claims"][0]["status"], "partial")
        self.assertEqual(result["claims"][0]["coverage"], 0.5)
        self.assertEqual(result["claims"][1]["status"], "not_evaluable")

    def test_rejects_inconsistent_token_count(self):
        with self.assertRaisesRegex(ValueError, "token_count"):
            build_evidence_span(
                {
                    "source": "README.md",
                    "start": 1,
                    "end": 3,
                    "token_count": 3,
                    "text": "bad count",
                }
            )

    def test_candidate_keywords_include_dotted_and_hyphenated_components(self):
        self.assertEqual(
            extract_keywords("path.relative_to raw-span"),
            ["path.relative_to", "path", "relative_to", "raw-span", "raw", "span"],
        )


if __name__ == "__main__":
    unittest.main()
