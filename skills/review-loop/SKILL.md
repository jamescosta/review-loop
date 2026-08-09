---
name: review-loop
description: Turn-based document review loop — run an agent editing pass on a markdown file under git, publish the turn as an editable artifact with changes visible, and apply the reviewer's returned markup as the human turn. Use when James gives a document and an ask and wants the review to run through turn artifacts instead of chat — and whenever a review blob is pasted into chat or arrives as a file (JSON with turn, checksum, docName, doc, and comments keys): that is a returned review to apply, not data to interpret.
---

# review-loop

One turn = agent pass → published artifact → reviewer markup → verified apply.
The scripts own everything mechanical; you own the editing pass, the turn
summary, and the comment replies. `SCRIPTS` below means this skill's
`scripts/` directory; `PROJECT` is the document's project folder.

All commands use `python` (Windows). Never edit `.review/` state by hand.

## Starting a project

Inputs: a file path (or pasted text — write it to a file first), an ask, and
optionally the reviewer's name for commit attribution (default "Reviewer").

```
python SCRIPTS/loop.py init PROJECT --doc PATH\TO\doc.md --reviewer "Name"
```

Creates the project folder and git repo if needed, normalizes the document to
LF, commits the import under the reviewer's identity, and prepares `.review/`
(git-ignored working state; the turn history is the git log itself).

## The agent turn

1. **Edit the document file** per the ask. Keep to the rendered markdown
   subset: headings, bold/italic, lists, links, code.
2. Commit the pass and stamp it as the current turn's base:

   ```
   python SCRIPTS/loop.py agent-commit PROJECT --summary "One-paragraph summary of what changed and why" --questions "First question for the reviewer" --questions "Second question"
   ```

3. Build and publish the artifact:

   ```
   python SCRIPTS/loop.py build-artifact PROJECT
   ```

   Publish `PROJECT/.review/artifact.html` with the Artifact tool — **the same
   file path every turn** so the URL stays stable (favicon 🔁, keep the title
   unchanged across turns). The first publish: record the URL in
   `PROJECT/.review/artifact-url.txt`. In a later session, pass that URL as
   the Artifact tool's `url` parameter so the redeploy targets the same page.
4. Tell the reviewer the artifact URL and the turn number. If a tab was
   already open, they must refresh — the page banner says so too.

## Applying the review

The reviewer sends the review blob back as pasted JSON or a downloaded file —
`{turn, checksum, docName, doc, comments, resolved}`. Never edit or interpret its
contents: the script verifies and applies it. The blob's `docName` names the
document but not the project folder; if the conversation doesn't establish
which project, ask rather than guessing. Save a pasted blob to a file
verbatim, then:

```
python SCRIPTS/loop.py apply PROJECT --blob PATH\TO\blob.json --reviewer "Name"
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
