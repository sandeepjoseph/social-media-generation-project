# Upstream synchronization workflow

The verified upstream for this codebase is `https://github.com/harry0703/MoneyPrinterTurbo`, default branch `main`. The workflow proposal assumes the named project is first established as a genuine public fork and that the fork's stable branch is named `main`.

The daily monitor fetches the upstream branch, compares its merge base with the fork's `main`, classifies changed paths, and tests a clean merge candidate in a separate job with read-only repository permissions. For a clean merge, it opens a review pull request from a SHA-named branch. The pull request includes a path-only impact report and test status. It never merges a pull request, rewrites an existing branch, or force-pushes. A merge conflict keeps the impact report as a workflow artifact, fails the workflow with a human-action message, and skips branch/PR creation until the merge is resolved and tested manually.

The prepare-review job has only `contents: write` and `pull-requests: write`, runs after the read-only inspection job, and does not execute incoming application code. Checkout credentials are not persisted. The CI workflow has `contents: read` only. Third-party actions are pinned to verified commit SHAs and labeled with their upstream release tags.

Before adopting this staging proposal, compare it with the fork's current default branch and repository policies. In particular, validate that `main` remains the stable base, GitHub Actions are enabled, and the named upstream is still correct. Repository code is not changed until fork establishment and this review are complete.

## Review policy

Path classification is a triage aid, not an approval. Runtime, dependency, workflow, authentication, and security changes always need review. Unknown paths are classified as application customization changes and require review. No category is auto-merged. CI covers regression tests and Ruff; integration tests requiring provider credentials or paid services are deliberately excluded.

## Shallow clones and isolated work

Use a new full-history clone or unshallow an isolated clone before history-sensitive synchronization. Do not unshallow or change remotes in a production checkout while jobs are running. For implementation, create a separate worktree from the fork's stable branch after upstream history is available; transfer only reviewed changes and preserve all existing dirty work in its original checkout.
