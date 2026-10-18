from app.services.studio_engagement import DEFAULT_POLICY, engagement_plan


def test_youtube_kids_restrictions_override_requested_engagement():
    for platform in ("youtube_long", "youtube_short"):
        result = engagement_plan(
            platform, {"made_for_kids": True, "reviewed": True}, DEFAULT_POLICY
        )
        assert result["comments"]["requested"] is True
        assert result["comments"]["action"] == "unavailable_made_for_kids"
        assert (
            result["subscriber_notifications"]["action"] == "unavailable_made_for_kids"
        )
        assert result["preserve_accurate_audience"] is True


def test_unreviewed_audience_cannot_enable_youtube_comments():
    result = engagement_plan("youtube_long", {"made_for_kids": False}, DEFAULT_POLICY)
    assert result["comments"]["action"] == "audience_review_required"


def test_supported_platforms_need_actual_settings_verification_and_viewer_consent():
    for platform in (
        "youtube_long",
        "facebook_reels",
        "instagram_reels",
        "tiktok",
        "dailymotion",
        "rumble",
    ):
        result = engagement_plan(
            platform, {"made_for_kids": False, "reviewed": True}, DEFAULT_POLICY
        )
        assert result["comments"]["action"] == "enable_if_supported_verify_in_platform"
        assert (
            result["subscriber_notifications"]["action"]
            == "opt_in_if_creator_control_exists"
        )
        assert (
            result["actual_platform_state"]
            == "not_verified_or_changed_by_metadata_preparation"
        )
        assert result["viewer_preferences_override_creator_request"] is True
        assert result["preserve_moderation_filters"] is True
