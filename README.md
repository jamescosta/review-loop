# review-loop

Turn-based document collaboration. Point Claude at a markdown document and an
ask: it takes an editing pass, commits it to git, and publishes the turn as a
web page where the changes are visible and you can edit the text and leave
comments anchored to what you selected. Send your markup back into the chat and
the loop verifies and applies it as the human turn, commits it under your name,
and replies to every thread on the next pass. The collaboration runs through
those turn pages instead of drafts pasted into chat, and the document itself
stays clean markdown with the whole history in git.

## Requirements

| Need | Why |
| :--- | :--- |
| Claude Code or Claude Cowork | Runs the skill and publishes the turn page |
| Python 3 | The scripts, standard library only — nothing to install |
| git 2.28 or newer | The turn history; `init` creates the repo with `git init -b` |
| A desktop browser | Where the reviewer reads the turn page and marks it up |

**GitHub is not required.** git runs locally on your machine — no account, no
remote, no push. The turn history lives in the project folder.

## Install

In Claude Code, add this repository as a plugin marketplace and install from
it:

```
/plugin marketplace add jamescosta/review-loop
/plugin install review-loop@jamescosta
```

`/plugin` is the interactive plugin panel in the Claude Code CLI. If the
install summary says `Run /reload-plugins to activate.`, run that. In the Claude
desktop app the same thing is done from **Customize → Plugins → Personal
plugins → + → Add marketplace → add from a repository**
([Use plugins in Claude](https://support.claude.com/en/articles/13837440-use-plugins-in-claude)).

Once installed, the skill fires on its own when you ask for document work;
`/review-loop:review-loop` invokes it by name.

### Without the plugin system

Copy the skill folder into your user skills directory instead:

```
mkdir -p ~/.claude/skills
rm -rf ~/.claude/skills/review-loop
cp -R skills/review-loop ~/.claude/skills/review-loop
```

```
New-Item -ItemType Directory -Force $env:USERPROFILE\.claude\skills | Out-Null
Remove-Item -Recurse -Force $env:USERPROFILE\.claude\skills\review-loop -ErrorAction SilentlyContinue
Copy-Item -Recurse skills\review-loop $env:USERPROFILE\.claude\skills\review-loop
```

Each line earns its place: the copy cannot create a missing `skills/` parent, and
it copies onto an existing install rather than into it — without the removal it
nests a second `review-loop/` inside the first and leaves the stale skill live.

Or invoke it in place by asking Claude to follow `skills/review-loop/SKILL.md`
on a document.

## Your first turn

`sample/doc.md` in this repository is a synthetic document to try it on; any
markdown file of your own works the same way.

1. Ask Claude: *start a review loop on `sample/doc.md` — tighten it and cut the
   repetition.*
2. Claude sets up the project, takes the first pass, publishes the turn page,
   and gives you the URL along with a summary of what changed and any questions
   — those live in chat, not on the page.
3. Open the URL. Toggle **Changes** to see what moved, **Clean** to read the
   result. Edit the text directly, and select any passage and **Add comment**
   to leave a note against it.
4. Press **Send review**, then **Copy to clipboard** (or **Download file**), and
   paste it back into the chat.
5. Claude verifies the review, applies it, commits it under your name, and
   answers every comment thread on the next pass. Repeat from step 2 until you
   say done — the document file is the deliverable.

If a rejection comes back — wrong turn, damaged review, already applied, the
file changed outside the loop — it names the cause and the recovery step, and
nothing is partially applied.

## Where your documents live

One folder per document in a home of their own, by default
`~/Documents/review-loop/<doc-slug>/` (on Windows,
`C:\Users\<you>\Documents\review-loop\<doc-slug>\`). A project is never created
inside a git repository — `init` refuses rather than nesting one repository
inside another. Your original file is copied in, never edited in place; when
you are done, copy the finished document out to wherever it belongs.

A project costs about 200 KB on disk and grows a few KB per turn.

**Publishing puts the whole document online.** The turn page embeds the full
document in a claude.ai artifact page on your own account — private by default,
but readable by anyone holding the link, and the page's version history keeps
earlier turns. Use it on documents you are willing to have live there.

## Claude Cowork

Plugins install in Cowork the same way as in the desktop Chat tab, and the
skills a plugin bundles work across chat on the web, the Chat tab in Claude
Desktop, and Cowork
([Use plugins in Claude](https://support.claude.com/en/articles/13837440-use-plugins-in-claude)).
Two things about where the work runs bear on this skill
([Cowork architecture overview](https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview)):

- **Cloud sessions** run the agent loop and code execution on Anthropic
  infrastructure, in a sandbox created when the session starts and destroyed
  when it ends. A project folder holding turn history does not survive that.
- **Desktop sessions** run the agent loop natively on your device, with shell
  commands and code executing in a per-session Linux VM.

**Unverified:** Anthropic's documentation does not state whether Python 3 and
git are available in that execution environment, whether code running there can
read and write your connected local folders, or whether the turn page can be
published from a Cowork session. Claude Code on the desktop is the supported
path. The empirical check is to run one turn in a Cowork session and see.

## Layout

- `skills/review-loop/` — the skill: `SKILL.md` plus `scripts/loop.py`
  (git plumbing, diffs, blob verification, apply) and
  `scripts/template.html` (the turn page).
- `.claude-plugin/` — `plugin.json` and the `marketplace.json` that makes this
  repository its own plugin marketplace.
- `tests/` — guard and normalization tests for the loop
  (`python -m pytest tests`), plus `tests/matcher/`, which replays the turn
  page's own anchor matcher under a DOM shim (`node tests/matcher/check.js`,
  `node tests/matcher/drift.js`, `python tests/matcher/mutate.py`). Node runs
  that rig; the skill itself never needs it.
- `sample/doc.md` — synthetic sample document for trying the loop.

Design of record: Notion page "Review-loop prototype — skill + artifact
(design)".
