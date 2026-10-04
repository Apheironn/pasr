import unittest

from pasr.tokenize import (
    TiktokenTokenizer,
    Tokenizer,
    WhitespaceTokenizer,
    get_tokenizer,
)


class WhitespaceTokenizerTests(unittest.TestCase):
    def test_round_trips_learned_text(self):
        tok = WhitespaceTokenizer()
        ids = tok.encode("select the relevant raw spans")
        self.assertEqual(tok.decode(ids), "select the relevant raw spans")
        self.assertEqual(tok.count("select the relevant raw spans"), 5)

    def test_is_deterministic_for_same_input(self):
        tok = WhitespaceTokenizer(["alpha beta", "beta gamma"])
        self.assertEqual(tok.encode("alpha beta gamma"), tok.encode("alpha beta gamma"))

    def test_satisfies_tokenizer_protocol(self):
        self.assertIsInstance(WhitespaceTokenizer(), Tokenizer)


class TiktokenTokenizerTests(unittest.TestCase):
    def test_round_trips_and_counts(self):
        tok = TiktokenTokenizer()
        text = "def select_context(query: str) -> list[str]:  # noqa\n    return []\n"
        ids = tok.encode(text)
        self.assertEqual(tok.decode(ids), text)
        self.assertEqual(tok.count(text), len(ids))
        self.assertGreater(len(ids), 0)

    def test_handles_special_token_strings_without_raising(self):
        tok = TiktokenTokenizer()
        self.assertGreater(tok.count("<|endoftext|> literal marker in source"), 0)

    def test_satisfies_tokenizer_protocol(self):
        self.assertIsInstance(TiktokenTokenizer(), Tokenizer)


class GetTokenizerTests(unittest.TestCase):
    def test_default_is_tiktoken_and_cached(self):
        first = get_tokenizer()
        second = get_tokenizer("default")
        self.assertIs(first, second)
        self.assertIsInstance(first, TiktokenTokenizer)

    def test_whitespace_by_name(self):
        self.assertIsInstance(get_tokenizer("whitespace"), WhitespaceTokenizer)

    def test_unknown_name_raises(self):
        with self.assertRaisesRegex(ValueError, "unknown tokenizer"):
            get_tokenizer("bogus")


class TokenizerAdapterTests(unittest.TestCase):
    def test_plain_protocol_tokenizer_can_select_matching_raw_tokens(self):
        from pasr.candidates import generate_lexical_candidates

        class PlainTokenizer:
            def encode(self, text):
                return [ord(character) for character in text]

            def decode(self, ids):
                return "".join(chr(value) for value in ids)

        candidates = generate_lexical_candidates("alpha beta", "beta", PlainTokenizer(), "words.txt", 6)

        self.assertEqual([(item.start, item.end, item.text) for item in candidates], [(6, 10, "beta")])

    def test_internal_type_error_is_not_retried_as_keyword_incompatibility(self):
        from pasr._tokenize import encode_ids

        class FailingTokenizer:
            def encode(self, text, truncation=False, add_special_tokens=None):
                if add_special_tokens is not None:
                    raise TypeError("broken tokenizer state")
                return [1]

        with self.assertRaisesRegex(TypeError, "broken tokenizer state"):
            encode_ids(FailingTokenizer(), "alpha")


if __name__ == "__main__":
    unittest.main()
