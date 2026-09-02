import unittest

from pasr.chunker import RawSpan, chunk_text
from pasr.tokenize import WhitespaceTokenizer, get_tokenizer

TEXT = "alpha beta gamma\ndelta\nepsilon zeta eta theta iota\nkappa\n"


class ChunkerTests(unittest.TestCase):
    def test_line_additive_offsets_and_boundaries(self):
        tok = WhitespaceTokenizer()
        spans = chunk_text("f.py", TEXT, tokenizer=tok, block_size=4)

        self.assertEqual(
            [(s.line_start, s.line_end, s.token_start, s.token_end) for s in spans],
            [(1, 2, 0, 4), (3, 3, 4, 9), (4, 4, 9, 10)],
        )
        self.assertEqual(sum(s.token_count for s in spans), spans[-1].token_end)

    def test_spans_are_contiguous_and_reconstruct_the_file(self):
        tok = WhitespaceTokenizer()
        spans = chunk_text("f.py", TEXT, tokenizer=tok, block_size=4)

        for left, right in zip(spans, spans[1:], strict=False):
            self.assertEqual(left.line_end + 1, right.line_start)
            self.assertEqual(left.char_end, right.char_start)
            self.assertEqual(left.token_end, right.token_start)
        for span in spans:
            self.assertEqual(TEXT[span.char_start : span.char_end], span.text)
        self.assertEqual("".join(s.text for s in spans), TEXT)

    def test_over_long_line_becomes_its_own_block(self):
        tok = WhitespaceTokenizer()
        spans = chunk_text("f.py", TEXT, tokenizer=tok, block_size=4)

        long_line = next(s for s in spans if s.line_start == 3)
        self.assertEqual(long_line.line_start, long_line.line_end)
        self.assertGreater(long_line.token_count, 4)

    def test_is_deterministic(self):
        tok = WhitespaceTokenizer()
        a = chunk_text("f.py", TEXT, tokenizer=tok, block_size=4)
        b = chunk_text("f.py", TEXT, tokenizer=WhitespaceTokenizer(), block_size=4)
        self.assertEqual(a, b)

    def test_empty_text_returns_no_spans(self):
        self.assertEqual(chunk_text("f.py", "", tokenizer=WhitespaceTokenizer()), [])

    def test_rejects_non_positive_block_size(self):
        with self.assertRaisesRegex(ValueError, "block_size"):
            chunk_text("f.py", TEXT, tokenizer=WhitespaceTokenizer(), block_size=0)

    def test_provenance_string(self):
        spans = chunk_text("pkg/mod.py", TEXT, tokenizer=WhitespaceTokenizer(), block_size=4)
        self.assertEqual(spans[0].provenance, "pkg/mod.py:1-2")
        self.assertEqual(spans[1].provenance, "pkg/mod.py:3")

    def test_default_tiktoken_tokenizer_reconstructs_source(self):
        text = "".join(f"line number {i} with a few words\n" for i in range(120))
        spans = chunk_text("big.txt", text, block_size=64)

        self.assertGreater(len(spans), 1)
        self.assertEqual("".join(s.text for s in spans), text)
        self.assertTrue(all(isinstance(s, RawSpan) for s in spans))
        # line-additive total is within a few percent of the whole-file token count
        whole = get_tokenizer().count(text)
        additive = spans[-1].token_end
        self.assertLessEqual(abs(whole - additive), max(5, round(0.05 * whole)))


if __name__ == "__main__":
    unittest.main()
