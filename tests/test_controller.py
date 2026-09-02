import unittest

from pasr.controller import choose_selector_settings


class ContextBrokerControllerTests(unittest.TestCase):
    def test_static_controller_keeps_request_settings(self):
        decision = choose_selector_settings(
            controller="static",
            query="focused query",
            file_metadata=[{"size_bytes": 12000}],
            block_size=128,
            top_k=4,
            prefix_size=64,
            local_window_size=256,
        )

        self.assertEqual(decision.block_size, 128)
        self.assertEqual(decision.top_k, 4)
        self.assertEqual(decision.controller, "static")

    def test_heuristic_controller_increases_recall_for_broad_queries(self):
        decision = choose_selector_settings(
            controller="heuristic_v0",
            query="summarize schema fields settings and validation diagnostics",
            file_metadata=[{"size_bytes": 20000}],
            block_size=256,
            top_k=1,
            prefix_size=64,
            local_window_size=256,
        )

        self.assertEqual(decision.block_size, 256)
        self.assertEqual(decision.top_k, 5)
        self.assertIn("evidence-heavy query", " ".join(decision.reasons))


if __name__ == "__main__":
    unittest.main()
