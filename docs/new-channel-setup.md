# New laptop and separate channel

The public repository contains the reusable implementation. Commercial creative
rules belong in your private policy backup. Provider keys, social logins, bank
details and media are separate local data and are never included in a new channel.
The upstream software licence still applies; a media copyright credit does not
replace that software licence or establish ownership of folklore/third-party work.

## Install

Install Git, Python 3.11+, FFmpeg and the repository's documented system
dependencies. Clone your fork, check out the reviewed production branch/release,
then install the dependencies in a virtual environment:

```sh
git clone https://github.com/YOUR-ACCOUNT/social-media-generation-project.git
cd social-media-generation-project
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows use `py -3.11 -m venv .venv` and activate
`.venv\Scripts\Activate.ps1`. Keep this checkout separate from private channel
folders. Update the fork through reviewed upstream PRs; inspect release changes
before moving an active production. The build/profile hashes deliberately hold
existing approvals when implementation or creative policy changes.

## Reuse private production rules

Clone your private policy repository outside this public checkout. A policy
backup needs the profile, director template and learning JSON files together.
The initializer resolves those dependencies from the backup's directory, so old
laptop paths do not have to exist. It copies only reusable creative fields and
applied learning, creates an empty asset registry, and discards accounts, media,
credentials, experimental approvals and old job state.

```sh
python -m app.services.studio_channel_setup init \
  --root "$HOME/StoryStudioChannels/my-new-channel" \
  --channel-id my-new-channel --channel-name "My New Channel" \
  --source-profile "$HOME/private-policy/brand-profile.json" \
  --rights-owner "Your Company Inc."
python -m app.services.studio_channel_setup launch \
  --root "$HOME/StoryStudioChannels/my-new-channel" --port 8511
```

Use the actual backup profile filename. Without `--source-profile`, initialization
uses a generic movie contract; your private direction and learned rules are not
available in the public repository. The same initializer is available in Director
Studio under **Set up a separate channel or another laptop**. Use port 8512 when
another channel is already running on 8511.

## Configure this channel

- Review the new private `brand-profile.json`: brand, rights owner, company credit,
  relevant brand hashtags and search keywords, languages, age group and media
  destination. Corporate credits stay configurable. The first-publication year is
  bound to each story, rather than changed on every subsequent packaging run.
- Enter new provider keys in this channel's local Studio settings. The launcher
  isolates `config.toml`, storage/database and cost overrides. Configure the
  provider's actual billing controls; a local policy is not a provider hard cap.
- Fill `accounts.json` with the intended public account identifiers for reference.
  It is an onboarding inventory, not an OAuth connector. Sign in to the intended
  brand accounts separately. Automated uploads require a supported adapter and
  platform authorization; Rumble remains a manual handoff without its permission.
- Category labels are suggestions: Education for educational stories, Film &
  Animation as a YouTube fallback, Digital creator/Education for applicable Meta
  profile categories, Entertainment/Education for Rumble. Some platforms expose
  no upload category. Select only labels actually offered; omit an unavailable
  optional secondary category. Monetization and payouts need separate approval.
- Restore/review reusable cast or set assets deliberately, with hashes and rights
  evidence, into the initially empty registry. Verify locale-specific captions,
  child-directed settings, AI disclosures, performance and full-film checks for
  each new release. No previous review or publication approval transfers.

Generated media goes to the new channel's own `media` directory, organized with
the existing date/story archive rules. `--media-root` can select another location.
Keep a backup of private policy and verified media; do not commit `config.toml`,
credentials or the full channel directory to the public fork. If moving an
initialized channel, launch rebases its private policy dependencies; review its
archive destination on the destination laptop before generation.

Copyright notices identify the owner-declared original production rights, to the
extent protected. Underlying folklore, licensed assets, provider terms and
third-party material retain their respective rights. A notice never clears
missing licences or proves copyrightability/ownership. The source/adaptation,
visual, voice and music evidence gates remain mandatory. See the
[Canadian Intellectual Property Office guide](https://ised-isde.canada.ca/site/canadian-intellectual-property-office/en/guide-copyright).
