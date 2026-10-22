# YouTube discovery as a reusable production step

Search visibility is observed separately from ranking. A metadata preflight
cannot force indexing, prove a ranking, or approve a movie's creative quality.
YouTube says new uploads and changed metadata can take a few days to appear.

New-channel initialization enables `search_policy.required` by default. Existing
private profiles can enable it explicitly. Frozen jobs need an explicit replan
on policy/build drift, preserving earlier media and reviews. Approval binds to
the exact rendered metadata, media and captions; a search edit invalidates an
earlier package approval. It does not clear creative publication holds.

## Prepare

Store reusable subject spellings in private `search_policy.subject_aliases`:

```json
{
  "required": true,
  "lead_characters": 300,
  "subject_aliases": [
    {"subject": "Mira", "aliases": ["Meera"]}
  ]
}
```

An alias group activates only when its subject/alias is in the story. It is
editorial configuration, not evidence of search volume. Review copied subject
groups for each new channel. No account IDs, keys or old observations transfer.

The request or prepared publication JSON can contain:

```json
{
  "search_brief": {
    "primary_query": "Mira",
    "episode_query": "Lost Thread",
    "aliases": ["Meera"]
  },
  "platform_titles": {
    "youtube_long": "Mira and the Lost Thread | A Story About Helping"
  },
  "platform_descriptions": {
    "youtube_long": "Mira follows a lost thread to help her neighbour. This story explores asking questions and helping others."
  }
}
```

Use one main subject and a specific, story-supported episode phrase. Prefer a
natural title and unique opening description, with corporate/copyright credits
and a few relevant hashtags after the story. Generated default descriptions
do this automatically; supplied descriptions are validated rather than silently
rewritten. The required check holds mismatched copy and metadata limits.
Spelling aliases go in bounded YouTube tags; do not fill descriptions with a
keyword list. Tags have a limited role compared with titles, thumbnails and
descriptions. Preserve accurate language, child-directed and AI settings.

Director Studio's Packaging tab displays/downloads the preflight and a search
test link. It also records actual observation receipts separately from approval.
No generation credits, API tokens, scraping or recurring monitoring are used.

## Verify after publication

1. Confirm the exact video ID in Studio, Public visibility, processing and any
   restrictions/errors. Review the rendered title, description and caption locale.
2. Test exact ID, channel plus episode and broader subject/story searches
   separately. Record timestamp/timezone, query, browser/sign-in/region context,
   exact result URLs and an evidence reference. A query miss does not prove the
   video is unindexed; a query match does not establish universal rank.
3. Bind each receipt to `search_readiness.metadata_sha256`. Earlier observations
   cannot prove updated copy is live. Keep account screenshots outside the media
   delivery archive. The receipt validates consistency of operator-supplied
   evidence; it does not independently authenticate that evidence.
4. Allow a few days after upload/edits. Use Studio Analytics' YouTube Search terms,
   impressions, CTR and retention when enough data exists. Unknown measurements
   stay unknown. Test one truthful title/thumbnail treatment at a time and record
   before/after dates. Do not promise a first result or manufacture engagement.

This is YouTube preparation, not Google Search Console submission. The pipeline
has no YouTube force-index function. All platform handoff, rights, audience,
caption, actual performance and final-film gates remain independent.

## Comments and notifications

The portable `engagement_policy` requests comments and creator publication
notifications wherever permitted. Each package records a per-platform handoff
plan, not a claim that a live switch was changed. Existing moderation filters
stay intact. YouTube disables comments and notifications on Made for Kids videos;
the pipeline preserves the accurate audience classification. Other platforms
require checking actual account/post eligibility and available controls. Viewer
account/device notification preferences and platform delivery limits still apply.
Do not resend old-post notifications or change privacy to force engagement.

See [YouTube audience restrictions](https://support.google.com/youtube/answer/9527654?hl=en)
and [subscriber notifications](https://support.google.com/youtube/answer/7389684?hl=en).

Official references, reviewed 2026-10-18:

- [Search visibility](https://support.google.com/youtube/answer/58097?hl=en)
- [Descriptions](https://support.google.com/youtube/answer/12948449?hl=en)
- [Tags](https://support.google.com/youtube/answer/146402?hl=en)
- [Performance and ranking](https://support.google.com/youtube/answer/141805?hl=en)
