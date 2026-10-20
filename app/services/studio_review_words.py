"""Reject contradictory review transcripts; matching words never proves lip sync."""

import re
import unicodedata


def spoken_tokens(text, locale="en"):
    if not isinstance(text, str):
        return []
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    english = isinstance(locale, str) and locale.split("-")[0].casefold() == "en"
    if english:
        # Only unambiguous common spoken contractions and spelling differences.
        # Keep word order, negation, repetitions, fillers and additional clauses.
        contractions = {
            "i'm": "i am",
            "i've": "i have",
            "i'll": "i will",
            "you're": "you are",
            "you've": "you have",
            "you'll": "you will",
            "we're": "we are",
            "we've": "we have",
            "we'll": "we will",
            "they're": "they are",
            "they've": "they have",
            "they'll": "they will",
            "don't": "do not",
            "doesn't": "does not",
            "didn't": "did not",
            "isn't": "is not",
            "aren't": "are not",
            "wasn't": "was not",
            "weren't": "were not",
            "won't": "will not",
            "can't": "can not",
            "cannot": "can not",
            "couldn't": "could not",
            "shouldn't": "should not",
            "wouldn't": "would not",
            "haven't": "have not",
            "hasn't": "has not",
            "hadn't": "had not",
            "let's": "let us",
        }
        for source, replacement in contractions.items():
            text = re.sub(r"(?<!\w)" + re.escape(source) + r"(?!\w)", replacement, text)
        text = re.sub(r"\bhand[- ]spans\b", "handspans", text)
    text = text.replace("'", "")
    # Python's \w excludes combining vowel marks in scripts such as Malayalam.
    # Keep letters, marks and numbers intact so different spoken words cannot
    # collapse to the same consonants during a multilingual review.
    tokens = "".join(
        ch if unicodedata.category(ch)[0] in {"L", "M", "N"} else " " for ch in text
    ).split()
    if english:
        numbers = {
            str(i): word
            for i, word in enumerate(
                (
                    "zero",
                    "one",
                    "two",
                    "three",
                    "four",
                    "five",
                    "six",
                    "seven",
                    "eight",
                    "nine",
                    "ten",
                    "eleven",
                    "twelve",
                )
            )
        }
        tokens = [numbers.get(t, t) for t in tokens]
    return tokens


def review_word_issues(expected, document, shot_id, *, locale="en"):
    """A curator's pass cannot override missing or different reported words.

    The caller must separately bind the exact source/review hashes, inspect
    independent wording evidence, and require actual audiovisual acceptance.
    This negative guard detects cross-shot contamination and omitted repeats.
    """
    if not isinstance(document, dict):
        return ["Native source review must be a structured document"]
    rows = document.get("shots")
    if rows is None:
        rows = [document]
    if not isinstance(rows, list):
        return ["Native source review must identify the reviewed shot"]
    matches = [r for r in rows if isinstance(r, dict) and r.get("shot_id") == shot_id]
    if len(matches) != 1:
        return ["Native source review must identify one unambiguous shot transcript"]
    heard = matches[0].get("heard_words")
    if not isinstance(heard, str) or not heard.strip():
        return ["Native source review must report the complete heard words"]
    if spoken_tokens(heard, locale) != spoken_tokens(expected, locale):
        return [
            "Native source review words contradict the scripted utterance; re-review the exact source"
        ]
    return []
