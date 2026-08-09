# Replaying a full turn

Commands run from the repo root; `python` is the Windows launcher. The
proof run's git history lives in `proof-run/` (git-ignored working area).
Replaying into a fresh folder reproduces it from scratch.

## 1. Start a project from the sample document

```
python skills/review-loop/scripts/loop.py init replay-run --doc sample/doc.md --reviewer "Proof Reviewer"
```

## 2. Agent pass

Edit `replay-run/doc.md` (the proof run changed the lease step, the lumber
line, and the closing paragraph), then:

```
python skills/review-loop/scripts/loop.py agent-commit replay-run --summary "What changed and why"
python skills/review-loop/scripts/loop.py build-artifact replay-run
```

Publish `replay-run/.review/artifact.html` with the Artifact tool and open
the URL. Record the URL in `replay-run/.review/artifact-url.txt`.

## 3. Review in the artifact

Edit in clean view, select text and comment, then Send review. Copy the
blob (it is pre-selected in the send dialog) and save it to a file.
`sample/review-blob.json` is the blob captured in the proof run — it edits
"Recruit ten" to "Recruit twelve" and comments on "clerk". It only applies
to a turn whose base matches its checksum (`f5809325`); against any other
turn it demonstrates the stale-turn / checksum rejections instead.

## 4. Apply the human turn

```
python skills/review-loop/scripts/loop.py apply replay-run --blob sample/review-blob.json --reviewer "Proof Reviewer"
```

Guards to try: apply the same blob twice (already-applied rejection), edit
the blob's turn number (stale rejection), delete characters from the doc
field (checksum rejection), or touch `replay-run/doc.md` before applying
(mid-turn collision).

## 5. Close the turn

```
python skills/review-loop/scripts/loop.py reply replay-run --thread c1-1 --body "The agent's reply"
```

Then the next agent pass (step 2) republishes the artifact at the same URL
with the reply threaded in.

## Proof-run evidence

`git -C proof-run log` shows the loop's provenance shape:

```
Proof Reviewer     | Turn 1 (review): 1 changed, 0 inserted, 0 deleted block(s)
Review-loop agent  | Turn 1 (agent): Firmed the proposal up for a grant application: ...
Proof Reviewer     | Import doc.md into review loop
```

plus `Turn 2 (agent)` on top after the reply pass. The turn 2 artifact
shows the reviewer's comment with the agent's reply threaded beneath it,
flagged "commented text was edited away — was: 'clerk'" because turn 2's
edit removed the anchored word.
