# Reviewed native generation batches

Cinema contract 3.3.0 releases the two designated speaking pilots first. After
that accepted source-bound pilot, each exported handoff permits at most four new
shots (a private policy may lower the limit to one, two or three). A completed
source awaiting review, a changed/missing source, or a negative current review
holds the next handoff. A matching saved take still blocks duplicate generation;
review is never inferred from its existence or ASR alone.

In Director Studio, export the current Flow bundle, submit only its allowed
shots under a separately approved live quote and bounded budget, and import the
native originals with exact preflight attestations. Prepare the blank batch
review and inspect every source at normal and half speed. Fill actual
observations and keep unintended words, corrupted text, extra actors, tracking,
prop changes and all other findings. Do not turn the blank defaults into a
positive review without real viewing/listening. Wordless physical shots need
actual material/action/sound observations rather than fabricated phoneme checks.

Use **Import native batch review**, or
`import_performance_batch_review(store, story_id, review)`. Supply one to four
non-pilot `batch_shot_ids`, the exact story/storyboard/policy hashes, reviewer and
one source-hashed row per selected shot. Per-row acceptance requires complete
normal/half review, physical tracking, correct cast/props, native timing and
three concrete numeric observations. Speaking rows also require exact words,
correct speaker/voice, complete utterance and lip-sync review. Unresolved
`observed_issues`, `curation_issues` or negative flags reject acceptance even
when the top status says passed. The import preserves failed evidence. A later
negative bound to current sources holds further work and invalidates downstream
approval phases; it does not remove published posts or original files.

Re-export only after the current delivered batch has passed. An early re-export
may hold all new shots until the already delivered subset is reviewed. Re-export
of a fully received, byte-verified story preserves its completed receipt phase;
it does not manufacture creative approval. Every complete-film, join, caption,
sound, rights, audience, archive and publication check remains mandatory. A
batch pass is never a final-film or monetization approval.

Provider account and content-policy holds survive re-export. Record a content
rejection using a Flow receipt with `provider_content_policy_rejected: true`;
resolve it directly with the provider instead of changing wording to evade a
filter. Account-check receipts retain their existing manual-resolution path.
No automatic provider request, retry, purchase or publishing adapter is added.
Unrecorded external clicks are outside this software boundary; it cannot
promise a provider billing cap.

This contract changes implementation/profile identity. Adopt it at an idle
checkpoint, preserve the previous media and evidence, and explicitly replan and
revalidate active jobs. Historical approvals do not silently transfer to 3.3.0.
Channel rules, original prompts, source catalogs and account evidence remain in
private storage. Another channel receives the same generic gates through its
enabled cinema contract and supplies its own policy, assets and accounts.
