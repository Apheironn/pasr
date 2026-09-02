"""Text processing utilities."""


def tokenize_a_sentence_into_lowercase_words(sentence):
    return [w for w in sentence.lower().split() if w.isalpha()]


def summarize_a_document_into_a_short_abstract(doc, limit):
    return doc[:limit].rsplit(" ", 1)[0] + " ..."


def transliterate_accented_characters_to_ascii(text):
    import unicodedata

    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def redact_personally_identifiable_information(text):
    import re

    return re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[redacted]", text)
