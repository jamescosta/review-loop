# Changelog

## 0.1.1

- **The turn page declares its own character encoding.** Hosts that serve the
  page raw — Cowork's artifact gallery, a local file — gave the browser no
  encoding to go on; a wrong guess shifted every multi-byte character and the
  page's self-check refused the turn as corrupt. Found by the first live Cowork
  run.
- **README's Cowork section states what that run established**: Python and git
  present, publishing via Cowork's artifact gallery, project folder
  session-lived.

## 0.1.0

The review-loop skill, packaged as a Claude Code plugin.

- **The loop** — `init`, `agent-commit`, `build-artifact`, `apply`, `reply` and
  `status`. One turn is an agent pass committed to git, a published turn page,
  the reviewer's markup, and a verified apply. A review that names the wrong
  turn, arrives damaged, was already applied, or lands on a file changed
  outside the loop is rejected with its cause and changes nothing.
- **The project guard** — one folder per document under
  `~/Documents/review-loop/`, never inside a git repository: `init` refuses
  rather than nesting one repository in another or sweeping a repository's
  uncommitted work into the document's history. The document is copied in, so
  the user's original file is never touched.
- **The turn page** — a single scrolling column pair, clean and changed views
  of the same document, selection-anchored comments with in-thread replies, and
  one mirrored block model driving both panes.
- **Cross-platform** — Windows, macOS and Linux, each exercised by CI.
