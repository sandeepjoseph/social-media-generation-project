# Market preferences and confirmed media cleanup

Keep channel-specific markets, languages and retention preferences in the external
private profile. `audience_strategy` and `media_retention_policy` are copied by
fresh channel setup, frozen in each story and bound into each platform package.
Changing them requires a new package approval; it does not change old uploads.
These modules are covered by the implementation-content identity.

`studio_audience.audience_distribution_plan` produces editorial preferences and
keeps actual country performance unknown. Organic geographic delivery is not
guaranteed. The module neither changes the creator's account residence nor buys
advertising, excludes viewers or infers inauthentic traffic from nationality.
Use actual platform country/watch-time/retention/traffic reports. A release window
is an experiment, not a proven best time. `release_window` converts its market
timezone to the operator's timezone with the correct date and DST.

```python
from app.services.studio_audience import release_window

proposal = release_window("2026-11-23", {
    "primary_country": "IN",
    "release_timezone": "Asia/Kolkata",
    "release_window": {"start": "18:00", "end": "20:00"},
})
```

`studio_retention.cleanup_plan` is a dry run. Supply one exact release/master,
explicit media roots and path/hash candidates, required platform names and
matching `public_verified` receipts with public watch URLs and observation times.
Missing platforms, changed hashes, symlinks, outside paths or documents hold the
plan. Never satisfy a new edition with an old edition's post receipts.

Present the complete path/hash/size list and space to reclaim to the owner only
after the publication gate passes. `validate_owner_confirmation` checks that a
real owner-message reference and explicit approval bind that unchanged plan.
There is deliberately no automatic deletion function or recursive directory
cleanup. An operator uses its authorized filesystem tool only after the actual
human confirmation. Preserve code, policies, scripts, captions, rights, reviews,
publication receipts and deletion tombstones in the appropriate Git repository.
Deleted media must be recorded as unavailable locally, not re-certified by a
historical archive check. Restoring code and policy does not restore old media,
Studio databases, credentials, sessions or historical creative approvals.

Review the original provider, native dialogue, small-batch and full-film gates
before any new generation. This feature does not lower them or authorize spend.
