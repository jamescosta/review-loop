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
- `sample/doc.md` — synthetic sample document for trying the loop.
- `proof-run/` — git-ignored working area holding the proof run's own git
  history (agent commits, reviewer-applied commits, threaded replies).

## Install

The skill is not installed anywhere by default. To use it from Claude Code,
copy the folder into your user skills directory:

```
cp -R skills/review-loop ~/.claude/skills/review-loop
```

```
Copy-Item -Recurse skills\review-loop $env:USERPROFILE\.claude\skills\review-loop
```

or invoke it in place by asking Claude Code to follow
`skills/review-loop/SKILL.md` on a document.

## Running a turn

`skills/review-loop/SKILL.md` is the complete flow — point a Claude Code
session at it with a document (start with `sample/doc.md`) and an ask.
