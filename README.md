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
| Claude Code | Runs the skill and publishes the turn page |
| Python 3 | The scripts, standard library only — nothing to install |
| git 2.28 or newer | The turn history; `init` creates the repo with `git init -b` |
| A desktop browser | Where the reviewer reads the turn page and marks it up |

**GitHub is not required.** git runs locally on your machine — no account, no
remote, no push. The turn history lives in the project folder.

**Cowork runs the loop too, with one caveat.** Its execution environment has
Python and git and turns publish through Cowork's own artifact gallery, but the
project folder only lives as long as the session — see the Cowork section.

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
   repetition.* Say who you are in that first message if you want the turns
   committed under your name; without one they are attributed to "Reviewer".
2. Claude sets up the project, takes the first pass, publishes the turn page,
   and gives you the URL along with a summary of what changed and any questions
   — those live in chat, not on the page.
3. Open the URL. Toggle **Changes** to see what moved, **Clean** to read the
   result. Edit the text directly, and select any passage and **Add comment**
   to leave a note against it. Put the caret in a table cell and a small strip
   of controls appears above the table for adding and removing rows and columns.
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
A live Cowork session established what the
[architecture overview](https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview)
leaves unstated:

- **The execution environment has what the loop needs.** Python 3 and git are
  present; project setup, the agent pass, and the turn-page build run
  unmodified.
- **Publishing goes through Cowork's artifact gallery.** Cowork has no
  claude.ai Artifact tool; the turn page becomes a Cowork artifact with a
  stable id across redeploys, and `.review/artifact-url.txt` records that
  reference. The page declares its own character encoding, so it renders
  intact served this way.
- **The project folder is session-lived.** Code executes against a sandboxed
  filesystem, not your desktop folders — cloud sandboxes are destroyed when
  the session ends, and desktop sessions execute in a per-session VM. Turn
  history does not outlive the session: before ending one, ask the agent to
  write the finished document out to a folder of yours. For a loop that spans
  sessions, run it in Claude Code on the desktop.

## Layout

- `skills/review-loop/` — the skill: `SKILL.md` plus `scripts/loop.py`
  (git plumbing, diffs, blob verification, apply) and
  `scripts/template.html` (the turn page).
- `.claude-plugin/` — `plugin.json` and the `marketplace.json` that makes this
  repository its own plugin marketplace.
- `tests/` — guard and normalization tests for the loop
  (`python -m pytest tests`), plus `tests/matcher/`, which runs the turn page's
  own code under a DOM shim: the anchor matcher (`node tests/matcher/check.js`,
  `node tests/matcher/drift.js`, `python tests/matcher/mutate.py`) and the block
  model against `tests/vectors.json`, the vector list both runtimes are pinned
  to (`node tests/matcher/roundtrip.js`). Node runs that rig; the skill itself
  never needs it.
- `sample/doc.md` — synthetic sample document for trying the loop.

Design of record: Notion page "Review-loop prototype — skill + artifact
(design)".
