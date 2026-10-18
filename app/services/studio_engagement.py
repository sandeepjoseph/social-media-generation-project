"""Creator engagement preferences, never a claim that live settings changed."""

DEFAULT_POLICY = {
    "comments_where_permitted": True,
    "subscriber_notifications_where_permitted": True,
    "preserve_moderation_filters": True,
    "respect_viewer_preferences": True,
}
YOUTUBE_AUDIENCE_SOURCE = "https://support.google.com/youtube/answer/9527654?hl=en"
YOUTUBE_NOTIFICATION_SOURCE = "https://support.google.com/youtube/answer/7389684?hl=en"


def engagement_plan(platform, audience, policy=None):
    policy = policy or {}
    comments = policy.get("comments_where_permitted") is True
    notifications = policy.get("subscriber_notifications_where_permitted") is True
    youtube = platform.startswith("youtube_")
    reviewed = audience.get("reviewed") is True and isinstance(
        audience.get("made_for_kids"), bool
    )
    kids = audience.get("made_for_kids") is True
    if youtube and kids:
        comment_status = notification_status = "unavailable_made_for_kids"
    elif youtube and not reviewed:
        comment_status = notification_status = "audience_review_required"
    else:
        comment_status = (
            "enable_if_supported_verify_in_platform"
            if comments
            else "no_change_requested"
        )
        notification_status = (
            "opt_in_if_creator_control_exists"
            if notifications
            else "no_change_requested"
        )
    return {
        "comments": {"requested": comments, "action": comment_status},
        "subscriber_notifications": {
            "requested": notifications,
            "action": notification_status,
        },
        "preserve_moderation_filters": True,
        "preserve_accurate_audience": True,
        "viewer_preferences_override_creator_request": True,
        "actual_platform_state": "not_verified_or_changed_by_metadata_preparation",
        "sources": [YOUTUBE_AUDIENCE_SOURCE, YOUTUBE_NOTIFICATION_SOURCE]
        if youtube
        else [],
        "handoff": "Check existing posts and future-upload defaults in each platform. Enable comments only where permitted, preserving filters and privacy. Opt in to creator publication notifications when offered and eligible. Do not change child-directed classification, force viewer alerts, resend old-post notifications, or claim delivery. Platform/account limits still apply.",
    }
