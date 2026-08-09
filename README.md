# review-loop

Prototype of a turn-based document review loop: a Claude Code skill runs an
agent's editing pass on a markdown file under git, publishes each turn as an
editable artifact (changes visible, selection-anchored comments), and applies
the reviewer's returned markup as the human turn. Purpose is insight, not
product.

Spec of record: Notion page "Review-loop prototype — skill + artifact (design)".

## Layout

- `skills/review-loop/` — the skill: `SKILL.md` plus `scripts/loop.py`
  (git plumbing, diffs, blob verification, apply) and
  `scripts/template.html` (the artifact page).
- `tests/` — guard and normalization tests (`python -m pytest tests`).
- `sample/` — synthetic sample document, a captured review blob, and
  `REPLAY.md` with the exact commands to replay a full turn.
- `proof-run/` — git-ignored working area holding the proof run's own git
  history (agent commit, review-applied commit, threaded turn 2).

## Install

The skill is not installed anywhere by default. To use it from Claude Code,
copy the folder into your user skills directory:

```
Copy-Item -Recurse skills\review-loop $env:USERPROFILE\.claude\skills\review-loop
```

or invoke it in place by asking Claude Code to follow
`skills/review-loop/SKILL.md` on a document.

## Running a turn

See `sample/REPLAY.md` for the end-to-end command sequence on the sample
document.
