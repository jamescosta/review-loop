# Changelog

## 0.1.3

- **The comment rail leaves the layout when it is empty.** A page with no
  threads held a 300px column open under a line of placeholder text, pushing
  the document off-center for the reading that most turns are. The rail now
  claims its track only once a thread exists or the comment form opens, and the
  document sits centered the rest of the time.

## 0.1.2

- **Tables render as tables.** A pipe table was a paragraph of literal pipes,
  and editing that paragraph flattened the whole table onto one line in the
  committed file. Tables are now their own block kind end to end, with column
  alignment preserved. Detection is strict — pipe-led rows, a delimiter row,
  no indentation — so anything ambiguous stays the paragraph it already was.
- **The reviewer can change a table's shape**, not just its text: putting the
  caret in a cell raises controls for adding and removing rows and columns.
  Deleting the header row or the last column is refused rather than performed.
- **Send checks the reviewer's own edits.** The load-time self-check only ever
  saw the base document, so markdown the page could not read back was shipped
  and committed, surfacing a turn later on a page that rebuilding could not
  fix. Send now refuses instead, while the edit is still on screen.
- **The mirror and the serializer are under test.** The block model is written
  twice, in `loop.py` and in `template.html`; both are now pinned to one vector
  list, and render/serialize are asserted to be inverses — the expression whose
  mismatch disables a turn page had no coverage at all.
- **Exotic characters normalize the same way in both block models.** A list
  marker written in Arabic-Indic digits was a list to the script and a paragraph
  to the turn page, and a line carrying U+0085, U+FEFF or U+001C-U+001F lost that
  character in one runtime and kept it in the other. Either way untouched text
  came back reading as an edit. Both character classes are spelled out now, and
  pinned to the shared vector list.

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
