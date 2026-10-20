import pytest

from app.services.studio_review_words import review_word_issues, spoken_tokens


def review(words):
    return {"shots": [{"shot_id": "a", "heard_words": words}]}


def test_orthography_and_unambiguous_contractions_do_not_change_audio_words():
    assert not review_word_issues(
        "I'm glad. Two handspans!", review("I am glad, 2 hand-spans."), "a"
    )
    assert spoken_tokens("നല്ല വാക്ക്.", "ml") == spoken_tokens("നല്ല വാക്ക്!", "ml")
    assert spoken_tokens("കുടം", "ml") != spoken_tokens("കടം", "ml")


@pytest.mark.parametrize(
    "heard",
    ["Perhaps a quicker grab. Quicker grab.", "Perhaps a grab.", "Do not grab it."],
)
def test_different_words_and_restarts_are_never_normalized_away(heard):
    assert review_word_issues("Perhaps a quicker grab.", review(heard), "a")


def test_missing_or_ambiguous_transcripts_are_held():
    assert review_word_issues("Hello.", {}, "a")
    assert review_word_issues("Hello.", review(""), "a")
    assert review_word_issues("Hello.", {"shots": review("Hello.")["shots"] * 2}, "a")
    assert not review_word_issues(
        "Hello.", {"shot_id": "a", "heard_words": "Hello!"}, "a"
    )
