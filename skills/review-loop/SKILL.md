---
name: review-loop
description: Turn-based document collaboration loop — the agent edits a markdown document under git, publishes each turn as an editable artifact with the changes visible, and applies the reviewer's returned markup as the human turn. Use whenever the user wants to create, draft, write, review, or revise a document, message, proposal, spec, or any prose deliverable — the collaboration runs through turn artifacts instead of drafts pasted into chat. Also use whenever a review blob is pasted into chat or arrives as a file (JSON with turn, checksum, baseChecksum, docName, doc, and comments keys): that is a returned review to apply, not data to interpret.
---

# review-loop

One turn = agent pass → published artifact → reviewer markup → verified apply.
The scripts own everything mechanical; you own the editing pass, the turn
summary, and the comment replies. `SCRIPTS` below means this skill's
`scripts/` directory; `PROJECT` is the document's project folder.

Never edit `.review/` state by hand.

## First run on a machine

The scripts need only Python 3 (standard library, nothing to install) and
git on PATH; publishing needs a surface that can publish an artifact page —
the Artifact tool in Claude Code, Cowork's artifact surface otherwise; the
reviewer needs a desktop browser. Before the first project on a machine, confirm the two
commands exist:

```
python --version     (some machines answer to python3 instead)
git --version        (2.28 or newer — init creates the repo with `git init -b`)
```

If either is missing, stop and tell the user what to install — Python from
python.org, git from git-scm.com — rather than failing mid-loop. Use
whichever Python spelling the machine answers to; examples below show
`python`.

## Where projects live

One folder per document, in a home of their own — default
`~/Documents/review-loop/<doc-slug>/` (on Windows,
`C:\Users\<you>\Documents\review-loop\<doc-slug>\`). Never put a project inside
a git repository: the loop commits with `git add -A`, which at a repository's
root sweeps that repository's uncommitted work into the document's history, and
below one buries a second repository inside the first. `init` refuses rather
than nesting.

`init` copies the document into the project, so the user's original file is
never touched. When the reviewer says done, copy the finished document out of
the project to wherever it should live.

A project runs about 200 KB on disk and grows a few KB per turn. The published
turn page and its version history live on the user's claude.ai account, not on
disk.

## Starting a project

Inputs: a file path (or pasted text — write it to a file first), an ask, and
optionally the reviewer's name for commit attribution (default "Reviewer").

```
python SCRIPTS/loop.py init PROJECT --doc PATH/TO/doc.md --reviewer "Name"
```

Creates the project folder and git repo if needed, normalizes the document to
LF, commits the import under the reviewer's identity, and prepares `.review/`
(git-ignored working state; the turn history is the git log itself).

## The agent turn

1. **Edit the document file** per the ask. Keep to the rendered markdown
   subset: headings, bold/italic, lists, links, code.
2. Commit the pass and stamp it as the current turn's base — the summary
   becomes the commit message:

   ```
   python SCRIPTS/loop.py agent-commit PROJECT --summary "One-paragraph summary of what changed and why"
   ```

3. Build and publish the artifact:

   ```
   python SCRIPTS/loop.py build-artifact PROJECT
   ```

   Publishing puts the whole document online: the turn page embeds the full
   document in a claude.ai artifact page, private by default but readable by
   anyone holding the link, and the page's version history retains earlier
   turns.

   Publish `PROJECT/.review/artifact.html` with the Artifact tool — **the same
   file path every turn** so the URL stays stable (pass favicon 🔁 to the
   Artifact tool, and keep the title
   unchanged across turns). The first publish: record the URL in
   `PROJECT/.review/artifact-url.txt`. In a later session, pass that URL as
   the Artifact tool's `url` parameter so the redeploy targets the same page.

   **In Cowork there is no Artifact tool.** Publish the same file through
   Cowork's artifact surface instead, and hold to the same invariants: one
   artifact, redeployed every turn — never a new one per turn — and its
   reference recorded in `PROJECT/.review/artifact-url.txt` in place of a
   claude.ai URL. The Cowork execution filesystem is session-scoped, so
   before the session ends, offer to write the finished document out to one
   of the user's connected folders.
4. Tell the reviewer the artifact URL and the turn number, and give the
   turn's summary and your questions **in chat** — the page deliberately
   carries neither. If a tab was already open, they must refresh (the page's
   Refresh button does it).

**One live surface.** The published URL is the loop's identity, and the
reviewer only ever sees the page through it. Never show `.review/artifact.html`
(or any rebuilt copy) to the reviewer in a local pane, preview, or second
publish — a page outside the published URL is a dead copy: it looks live,
carries no sign that it isn't, and every review sent from it is built on the
wrong state and bounces.

## Applying the review

The reviewer sends the review blob back as pasted JSON or a downloaded file —
`{turn, checksum, baseChecksum, docName, doc, comments, resolved}`. Never edit or interpret its
contents: the script verifies and applies it. The blob's `docName` names the
document but not the project folder; if the conversation doesn't establish
which project, ask rather than guessing. Save a pasted blob to a file
verbatim, then:

```
python SCRIPTS/loop.py apply PROJECT --blob PATH/TO/blob.json --reviewer "Name"
```

The script verifies before touching anything — wrong turn, damaged blob,
already-applied, or a file changed outside the loop are each rejected with
the cause and the recovery step, and a rejection never partially applies.
Relay a rejection's message to the reviewer verbatim.

On success it applies the reviewer's edits to the file, commits under their
name, marks any threads the reviewer resolved (those leave the next turn and
need no reply), and lists every comment thread awaiting a reply.

## Closing the turn

1. **Reply to every thread it lists** — substantively, as the agent:

   ```
   python SCRIPTS/loop.py reply PROJECT --thread ID --body "Your reply"
   ```

2. Take the next agent pass (back to "The agent turn") — address the edits
   and comments, answer the reviewer's questions in the new summary, and the
   replies render in-thread on the next artifact.

When the reviewer says done, the file is the deliverable — clean markdown,
full provenance in git. `python SCRIPTS/loop.py status PROJECT` shows turn
state at any point.
