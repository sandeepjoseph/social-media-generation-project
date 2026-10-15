# Preparing generic upstream contributions

Use the selector as a path filter, then review each candidate's code and history locally. The selector only prints committed path names, omits excluded paths entirely, and does not stage, export, or push anything.

Candidates should be small, independently useful improvements that fit MoneyPrinterTurbo's conventions. Keep story content, private prompts, credentials, configuration, account details, business policy, unpublished media, generated assets, and pricing or billing evidence out of contribution branches. Preserve the upstream license and attribution. Excluded paths must not be overridden manually until they have been checked for sensitive information and the owner has explicitly chosen to share them.

For a contribution, use a dedicated branch in an isolated full-history worktree, include only the approved source and tests, run the upstream-compatible test and lint commands, inspect the final diff and commit ancestry, and prepare a draft PR for human review. The staging workflow does not create or submit contribution PRs.
