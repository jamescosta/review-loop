import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "skills" / "review-loop" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import loop  # noqa: E402

LOOP = str(SCRIPTS / "loop.py")


def write_lf(path, text):
    # Deliberately independent of loop.write_text: fixtures must not depend
    # on the code under test.
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ------------------------------------------------------------- normalize

def test_normalize_joins_softwrapped_paragraphs():
    assert loop.normalize("one two\nthree") == loop.normalize("one  two three")


def test_normalize_crlf_and_nbsp():
    assert loop.normalize("a\r\nb\r\n\r\nc d") == "a b\n\nc d"


def test_normalize_list_markers_and_nesting():
    # Canonical markers ('-', '1.'); level = leading spaces // 2.
    a = "* one\n    2. two\n  - three"
    assert loop.normalize(a) == "- one\n    1. two\n  - three"


def test_normalize_list_continuation_merges():
    assert loop.normalize("- item\n  continued line") == "- item continued line"


def test_normalize_heading_block_splits_trailing_lines():
    assert loop.normalize("# Title\ntrailing text") == "# Title\n\ntrailing text"


def test_normalize_fence_verbatim():
    md = "```py\nx =  1\n\ny = 2\n```"
    assert loop.normalize(md) == md


def test_split_blocks_keeps_blank_lines_inside_fences():
    blocks = loop.split_blocks("para\n\n```\na\n\nb\n```\n\nafter")
    assert len(blocks) == 3
    assert blocks[1] == "```\na\n\nb\n```"


# ------------------------------------------------------------- checksum

def test_fnv1a_known_values():
    # Pinned values; template.html's fnv1a must produce the same.
    assert loop.fnv1a("") == "811c9dc5"
    assert loop.fnv1a("hello") == "4f9f2cab"
    assert loop.fnv1a("café\n") == "ff2f5979"


# ------------------------------------------------------------- diffs

def test_block_diff_shapes():
    old = "# T\n\nalpha beta gamma\n\n- a\n- b\n"
    new = "# T\n\nalpha BETA gamma\n\nnew para\n\n- a\n- b\n"
    d = loop.block_diff(old, new)
    assert [p["t"] for p in d] == ["eq", "chg", "ins", "eq"]
    chg = d[1]["ops"]
    assert ["del", "beta "] in chg and ["ins", "BETA "] in chg


def test_word_ops_ignore_rewrap_churn():
    ops = loop.word_ops("one two\nthree four", "one two three four")
    assert [op for op, _ in ops] == ["eq"]


def test_block_diff_lists_never_word_merge():
    d = loop.block_diff("- a\n- b\n", "- a\n- c\n")
    assert [p["t"] for p in d] == ["del", "ins"]


def test_reconstruct_ignores_dom_churn_but_applies_edits():
    base = "# Title\n\none  two\nthree\n\n- x\n- y\n"
    returned = "# Title\n\none two three\n\n- x\n- z\n"
    result, stats = loop.reconstruct(base, returned)
    # Churn-only paragraph keeps the base's raw text; edited list is replaced.
    assert "one  two\nthree" in result
    assert "- z" in result and "- y" not in result
    assert stats["changed"] == 1


# ---------------------------------------------------------- CLI end to end

def run(args, cwd=None):
    return subprocess.run([sys.executable, LOOP, *map(str, args)],
                          capture_output=True, text=True, cwd=cwd)


def make_blob(doc, turn, **overrides):
    blob = {"turn": turn, "checksum": loop.fnv1a(doc), "doc": doc, "comments": []}
    blob.update(overrides)
    return blob


def turn_base(project):
    return (project / ".review" / "base.md").read_text(encoding="utf-8")


def apply_blob(project, tmp_path, blob, reviewer="Test Reviewer"):
    bf = tmp_path / "blob.json"
    write_lf(bf, json.dumps(blob))
    return run(["apply", project, "--blob", bf, "--reviewer", reviewer])


def raw_payload(project):
    html = (project / ".review" / "artifact.html").read_text(encoding="utf-8")
    return html.split('<script id="rl-data" type="application/json">')[1] \
               .split("</script>")[0]


@pytest.fixture()
def project(tmp_path):
    src = tmp_path / "doc.md"
    write_lf(src, "# Sample\n\nfirst paragraph\n")
    proj = tmp_path / "proj"
    r = run(["init", proj, "--doc", src, "--reviewer", "Test Reviewer"])
    assert r.returncode == 0, r.stderr
    doc = proj / "doc.md"
    write_lf(doc, "# Sample\n\nfirst paragraph, improved\n")
    r = run(["agent-commit", proj, "--summary", "Improved the paragraph"])
    assert r.returncode == 0, r.stderr
    return proj


def test_agent_commit_identity_and_state(project):
    log = subprocess.run(["git", "-C", str(project), "log", "--format=%an|%s"],
                         capture_output=True, text=True).stdout.strip().split("\n")
    assert log[0] == "Review-loop agent|Turn 1 (agent): Improved the paragraph"
    assert log[-1] == "Test Reviewer|Import doc.md into review loop"
    state = json.loads((project / ".review" / "state.json").read_text())
    assert state["turn"] == 1 and state["applied"] is False


def test_build_artifact_embeds_escaped_data(project):
    r = run(["build-artifact", project])
    assert r.returncode == 0, r.stderr
    html = (project / ".review" / "artifact.html").read_text(encoding="utf-8")
    assert "__REVIEW_LOOP_DATA__" not in html and "__DOC_TITLE__" not in html
    payload = raw_payload(project)
    assert "<" not in payload  # embedding safety: `<` always escaped
    data = json.loads(payload)
    assert data["turn"] == 1 and data["checksum"] == loop.fnv1a(data["baseDoc"])


def test_apply_rejects_stale_turn(project, tmp_path):
    r = apply_blob(project, tmp_path, make_blob(turn_base(project), turn=7))
    assert r.returncode == 2
    assert "built on turn 7, current is 1" in r.stderr
    assert "refresh the artifact" in r.stderr


def test_apply_rejects_truncated_blob(project, tmp_path):
    raw = json.dumps(make_blob(turn_base(project), turn=1))
    bf = tmp_path / "blob.json"
    write_lf(bf, raw[: len(raw) // 2])  # cut mid-JSON
    r = run(["apply", project, "--blob", bf, "--reviewer", "Test Reviewer"])
    assert r.returncode == 2
    assert "truncated" in r.stderr and "send again" in r.stderr


def test_apply_rejects_checksum_mismatch(project, tmp_path):
    r = apply_blob(project, tmp_path,
                   make_blob(turn_base(project), turn=1, checksum="deadbeef"))
    assert r.returncode == 2
    assert "checksum" in r.stderr


def test_apply_rejects_mid_turn_file_collision(project, tmp_path):
    base = turn_base(project)
    write_lf(project / "doc.md", "# Sample\n\nchanged outside the loop\n")
    r = apply_blob(project, tmp_path, make_blob(base, turn=1))
    assert r.returncode == 2
    assert "changed outside the loop" in r.stderr
    assert "nothing was applied" in r.stderr
    # Nothing partially applied: state still open, no review commit.
    state = json.loads((project / ".review" / "state.json").read_text())
    assert state["applied"] is False


def test_apply_happy_path_then_already_applied(project, tmp_path):
    edited = turn_base(project).replace("improved", "improved and edited by the human")
    blob = make_blob(edited, turn=1, comments=[
        {"id": "c1-1", "reply_to": None,
         "anchor": {"text": "first paragraph", "occurrence": 0,
                    "before": "", "after": ", improved"},
         "body": "Why this wording?"}])
    r = apply_blob(project, tmp_path, blob)
    assert r.returncode == 0, r.stderr
    assert "edited by the human" in (project / "doc.md").read_text(encoding="utf-8")
    log = subprocess.run(["git", "-C", str(project), "log", "-1", "--format=%an|%ae|%s"],
                         capture_output=True, text=True).stdout.strip()
    assert log.startswith("Test Reviewer|test-reviewer@review-loop.local|Turn 1 (review):")
    threads = json.loads((project / ".review" / "comments.json").read_text())["threads"]
    assert threads[0]["id"] == "c1-1" and threads[0]["pending_reply"] is True

    # Re-sending the same blob is refused.
    r2 = apply_blob(project, tmp_path, blob)
    assert r2.returncode == 2
    assert "already applied" in r2.stderr and "re-send is refused" in r2.stderr

    # Reply threads, then the next agent turn carries them.
    r3 = run(["reply", project, "--thread", "c1-1", "--body", "Because X."])
    assert r3.returncode == 0
    threads = json.loads((project / ".review" / "comments.json").read_text())["threads"]
    assert threads[0]["pending_reply"] is False
    assert threads[0]["messages"][-1] == {"author": "agent", "body": "Because X."}


def test_resolve_flow(project, tmp_path):
    # Turn 1: a comment creates thread c1-1.
    blob = make_blob(turn_base(project), turn=1, comments=[
        {"id": "c1-1", "reply_to": None,
         "anchor": {"text": "first paragraph", "occurrence": 0,
                    "before": "", "after": ", improved"},
         "body": "A question"}])
    assert apply_blob(project, tmp_path, blob).returncode == 0

    # Turn 2: the reviewer resolves it.
    r = run(["agent-commit", project, "--summary", "next pass"])
    assert r.returncode == 0, r.stderr
    r = apply_blob(project, tmp_path,
                   make_blob(turn_base(project), turn=2, resolved=["c1-1"]))
    assert r.returncode == 0, r.stderr
    assert "Resolved thread(s): c1-1" in r.stdout
    threads = json.loads((project / ".review" / "comments.json").read_text())["threads"]
    assert threads[0]["resolved"] is True and threads[0]["pending_reply"] is False

    # Resolved threads leave the next turn's artifact data.
    run(["agent-commit", project, "--summary", "turn 3"])
    assert run(["build-artifact", project]).returncode == 0
    assert json.loads(raw_payload(project))["threads"] == []


def test_build_artifact_refuses_applied_turn(project, tmp_path):
    assert apply_blob(project, tmp_path,
                      make_blob(turn_base(project), turn=1)).returncode == 0
    r = run(["build-artifact", project])
    assert r.returncode == 2
    assert "already applied" in r.stderr and "agent-commit" in r.stderr


def test_apply_rejects_unknown_resolve_id(project, tmp_path):
    r = apply_blob(project, tmp_path,
                   make_blob(turn_base(project), turn=1, resolved=["no-such-thread"]))
    assert r.returncode == 2
    assert "unknown thread" in r.stderr
    state = json.loads((project / ".review" / "state.json").read_text())
    assert state["applied"] is False


def test_apply_rejects_malformed_comment_without_mutating(project, tmp_path):
    blob = make_blob(turn_base(project), turn=1, comments=[
        {"id": "c1-1", "reply_to": "no-such-thread", "body": "hello"}])
    r = apply_blob(project, tmp_path, blob)
    assert r.returncode == 2
    assert "unknown thread" in r.stderr
    state = json.loads((project / ".review" / "state.json").read_text())
    assert state["applied"] is False


def test_lf_discipline_end_to_end(project):
    # A CRLF file written mid-loop is normalized to LF by agent-commit.
    with open(project / "doc.md", "w", encoding="utf-8", newline="") as f:
        f.write("# Sample\r\n\r\ncrlf paragraph\r\n")
    r = run(["agent-commit", project, "--summary", "CRLF test"])
    assert r.returncode == 0, r.stderr
    raw = (project / "doc.md").read_bytes()
    assert b"\r" not in raw
