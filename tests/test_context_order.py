import unittest

from pasr.context_order import order_selected_spans, validate_context_order


class ContextOrderTests(unittest.TestCase):
    def setUp(self):
        self.spans = [
            {"source": "b.md", "abs_start": 20, "score": 0.7, "text": "b"},
            {"source": "a.md", "abs_start": 30, "score": 0.9, "text": "a2"},
            {"source": "a.md", "abs_start": 10, "score": 0.8, "text": "a1"},
            {"source": "c.md", "abs_start": 5, "score": 0.6, "text": "c"},
        ]

    def test_score_order_keeps_highest_scores_first(self):
        ordered = order_selected_spans(self.spans, top_k=3, context_order="score")

        self.assertEqual([span["score"] for span in ordered], [0.9, 0.8, 0.7])
        self.assertEqual([span["selection_rank"] for span in ordered], [1, 2, 3])
        self.assertEqual([span["context_position"] for span in ordered], [1, 2, 3])

    def test_source_order_keeps_top_k_then_restores_document_order(self):
        ordered = order_selected_spans(self.spans, top_k=3, context_order="source")

        self.assertEqual(
            [(span["source"], span["abs_start"]) for span in ordered],
            [("a.md", 10), ("a.md", 30), ("b.md", 20)],
        )
        self.assertEqual(sorted(span["selection_rank"] for span in ordered), [1, 2, 3])

    def test_edge_packed_puts_second_best_span_at_the_end(self):
        ordered = order_selected_spans(self.spans, top_k=4, context_order="edge_packed")

        self.assertEqual([span["score"] for span in ordered], [0.9, 0.7, 0.6, 0.8])
        self.assertEqual(ordered[0]["selection_rank"], 1)
        self.assertEqual(ordered[-1]["selection_rank"], 2)

    def test_diverse_order_avoids_single_source_collapse(self):
        spans = [
            {"source": "a.md", "abs_start": 10, "token_count": 20, "score": 0.99, "text": "a1"},
            {"source": "a.md", "abs_start": 40, "token_count": 20, "score": 0.98, "text": "a2"},
            {"source": "a.md", "abs_start": 80, "token_count": 20, "score": 0.97, "text": "a3"},
            {"source": "b.md", "abs_start": 10, "token_count": 20, "score": 0.96, "text": "b1"},
            {"source": "c.md", "abs_start": 10, "token_count": 20, "score": 0.95, "text": "c1"},
        ]

        ordered = order_selected_spans(spans, top_k=3, context_order="diverse")

        self.assertIn("b.md", {span["source"] for span in ordered})
        self.assertIn("c.md", {span["source"] for span in ordered})
        self.assertEqual(sorted(span["selection_rank"] for span in ordered), [1, 2, 3])
        self.assertEqual([span["context_position"] for span in ordered], [1, 2, 3])

    def test_rejects_unknown_context_order(self):
        with self.assertRaisesRegex(ValueError, "context_order must be one of"):
            validate_context_order("random")


if __name__ == "__main__":
    unittest.main()
