import json
import os
import shutil
import subprocess
import sys
import tempfile
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


def test_block_diff_heading_level_change_never_word_merges():
    # A level change rewrites the marker token; word-merging it would leave
    # the changes view unable to re-render the heading.
    d = loop.block_diff("## Title words here\n", "# Title words here\n")
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


def make_blob(doc, turn, base=None, **overrides):
    blob = {"turn": turn, "checksum": loop.fnv1a(doc),
            "baseChecksum": loop.fnv1a(doc if base is None else base),
            "doc": doc, "comments": []}
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


def test_init_refuses_to_nest_inside_a_git_repo(tmp_path):
    # The loop's `git add -A` must never reach a host repository's work.
    host = tmp_path / "host"
    host.mkdir()
    subprocess.run(["git", "-C", str(host), "init", "-q"], check=True,
                   capture_output=True)
    src = tmp_path / "doc.md"
    write_lf(src, "# Sample\n\nfirst paragraph\n")
    proj = host / "nested" / "proj"
    r = run(["init", proj, "--doc", src, "--reviewer", "Test Reviewer"])
    assert r.returncode == 2
    assert "inside a git repository" in r.stderr
    assert "~/Documents/review-loop" in r.stderr  # the recovery
    assert not (host / "nested").exists()  # refused before anything was created


def test_init_refuses_a_bare_repository(tmp_path):
    # A bare repo answers --is-inside-work-tree=false; only --is-inside-git-dir
    # catches it, and writing a project into one corrupts the repository.
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True,
                   capture_output=True)
    src = tmp_path / "doc.md"
    write_lf(src, "# Sample\n\nfirst paragraph\n")
    r = run(["init", bare / "proj", "--doc", src, "--reviewer", "Test Reviewer"])
    assert r.returncode == 2
    assert "inside a git repository" in r.stderr
    assert not (bare / "proj").exists()


def test_init_refuses_to_import_a_document_onto_itself(tmp_path):
    # Project == the document's own folder: the import would rewrite the
    # original through to_lf() instead of copying it.
    docs = tmp_path / "docs"
    docs.mkdir()
    src = docs / "doc.md"
    with open(src, "wb") as f:  # CRLF, no trailing newline — to_lf would change both
        f.write(b"# Sample\r\n\r\nfirst paragraph")
    before = src.read_bytes()
    r = run(["init", docs, "--doc", src, "--reviewer", "Test Reviewer"])
    assert r.returncode == 2
    assert "rewrite the original in place" in r.stderr
    assert src.read_bytes() == before  # the user's file is untouched


def test_init_refuses_a_damaged_repository_marker(tmp_path):
    # A .git file pointing at a missing gitdir draws a different "not a git
    # repository" message; reading it as a clean no would nest the project
    # inside a repository that is merely broken.
    broken = tmp_path / "broken"
    broken.mkdir()
    write_lf(broken / ".git", "gitdir: /nonexistent/path/to/gitdir\n")
    src = tmp_path / "doc.md"
    write_lf(src, "# Sample\n\nfirst paragraph\n")
    r = run(["init", broken / "proj", "--doc", src, "--reviewer", "Test Reviewer"])
    assert r.returncode == 2
    assert "could not tell whether" in r.stderr
    assert not (broken / "proj").exists()


def test_init_refuses_a_repository_with_a_stray_state_file(tmp_path):
    # The re-init exemption must not be claimable by a stray or half-written
    # state file: the host's own uncommitted work would be swept into the
    # import commit.
    host = tmp_path / "host"
    host.mkdir()
    subprocess.run(["git", "-C", str(host), "init", "-q"], check=True,
                   capture_output=True)
    (host / ".review").mkdir()
    write_lf(host / ".review" / "state.json", "{}\n")
    write_lf(host / "app.py", "print('work in progress')\n")
    src = tmp_path / "doc.md"
    write_lf(src, "# Sample\n\nfirst paragraph\n")
    r = run(["init", host, "--doc", src, "--reviewer", "Test Reviewer"])
    assert r.returncode == 2
    assert "inside a git repository" in r.stderr
    log = subprocess.run(["git", "-C", str(host), "log", "--oneline"],
                         capture_output=True, text=True)
    assert log.stdout.strip() == ""  # nothing of the host's was committed


def test_init_refuses_a_hard_linked_source(tmp_path):
    # Two paths, one inode: path equality misses it and the import would
    # truncate the user's original through the shared file.
    src = tmp_path / "doc.md"
    write_lf(src, "# Sample\n\nfirst paragraph\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    try:
        os.link(src, proj / "doc.md")
    except OSError:
        pytest.skip("filesystem does not support hard links")
    before = src.read_bytes()
    r = run(["init", proj, "--doc", src, "--reviewer", "Test Reviewer"])
    assert r.returncode == 2
    assert "rewrite the original in place" in r.stderr
    assert src.read_bytes() == before


@pytest.mark.parametrize("var", ["GIT_CEILING_DIRECTORIES", "GIT_OBJECT_DIRECTORY",
                                 "GIT_COMMON_DIR", "GIT_DIR", "GIT_WORK_TREE"])
def test_init_refuses_whatever_git_env_the_caller_exports(tmp_path, var):
    # Each of these hides the host repository from discovery, so the probe has
    # to answer about the path it was given, not the caller's git context.
    host = tmp_path / "host"
    (host / "sub").mkdir(parents=True)
    subprocess.run(["git", "-C", str(host), "init", "-q"], check=True,
                   capture_output=True)
    src = tmp_path / "doc.md"
    write_lf(src, "# Sample\n\nfirst paragraph\n")
    # A ceiling hides the host by naming it; the object/dir redirects hide it by
    # pointing discovery at somewhere that is not there.
    value = host if var == "GIT_CEILING_DIRECTORIES" else tmp_path / "missing"
    env = dict(os.environ, **{var: str(value)})
    proj = host / "sub" / "proj"
    r = subprocess.run([sys.executable, LOOP, "init", str(proj),
                        "--doc", str(src), "--reviewer", "Test Reviewer"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 2
    assert "inside a git repository" in r.stderr
    assert not proj.exists()


def test_init_never_writes_through_a_symlinked_destination(tmp_path):
    # An aliased destination must be replaced, not written through: the write
    # would truncate a file outside the project.
    external = tmp_path / "external.md"
    write_lf(external, "external content\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    try:
        os.symlink(external, proj / "doc.md")
    except OSError:
        pytest.skip("symlinks not permitted on this platform")
    src = tmp_path / "doc.md"
    write_lf(src, "# Sample\n\nimported paragraph\n")
    r = run(["init", proj, "--doc", src, "--reviewer", "Test Reviewer"])
    assert r.returncode == 0, r.stderr
    assert external.read_text(encoding="utf-8") == "external content\n"
    assert not (proj / "doc.md").is_symlink()
    assert "imported paragraph" in (proj / "doc.md").read_text(encoding="utf-8")


def test_rejected_init_leaves_a_symlinked_destination_in_place(tmp_path):
    # The destination is only replaced once the source has been read: a source
    # that cannot be decoded must not cost the user the link.
    external = tmp_path / "external.md"
    write_lf(external, "external content\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    try:
        os.symlink(external, proj / "doc.md")
    except OSError:
        pytest.skip("symlinks not permitted on this platform")
    src = tmp_path / "doc.md"
    src.write_bytes(b"\xff\xfe\x00not valid utf-8")
    r = run(["init", proj, "--doc", src, "--reviewer", "Test Reviewer"])
    assert r.returncode != 0
    assert (proj / "doc.md").is_symlink()
    assert external.read_text(encoding="utf-8") == "external content\n"


def test_init_succeeds_below_a_filesystem_boundary():
    # Discovery stopping at a mount reports a differently worded diagnostic, and
    # reading that as an unrecognized failure refuses an ordinary safe init.
    shm = Path("/dev/shm")
    if not (shm.is_dir() and os.access(shm, os.W_OK)):
        pytest.skip("no writable /dev/shm to sit below a mount point")
    area = Path(tempfile.mkdtemp(dir=str(shm)))
    try:
        src = area / "doc.md"
        write_lf(src, "# Sample\n\nfirst paragraph\n")
        r = run(["init", area / "proj", "--doc", src, "--reviewer", "Test Reviewer"])
        assert r.returncode == 0, r.stderr
        assert (area / "proj" / "doc.md").is_file()
    finally:
        shutil.rmtree(area, ignore_errors=True)


def test_init_reinits_an_existing_project(project, tmp_path):
    # The project is itself a git repo; the nesting guard must not fire on it.
    r = run(["init", project, "--doc", tmp_path / "doc.md",
             "--reviewer", "Test Reviewer"])
    assert r.returncode == 0, r.stderr


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
    base = turn_base(project)
    edited = base.replace("improved", "improved and edited by the human")
    blob = make_blob(edited, turn=1, base=base, comments=[
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


def test_apply_rejects_wrong_base(project, tmp_path):
    r = apply_blob(project, tmp_path,
                   make_blob(turn_base(project), turn=1, baseChecksum="deadbeef"))
    assert r.returncode == 2
    assert "different document base" in r.stderr
    state = json.loads((project / ".review" / "state.json").read_text())
    assert state["applied"] is False


def test_apply_rejects_duplicate_comment_ids_in_one_blob(project, tmp_path):
    anchor = {"text": "first paragraph", "occurrence": 0, "before": "", "after": ""}
    blob = make_blob(turn_base(project), turn=1, comments=[
        {"id": "c1-1", "reply_to": None, "anchor": anchor, "body": "one"},
        {"id": "c1-1", "reply_to": None, "anchor": anchor, "body": "two"}])
    r = apply_blob(project, tmp_path, blob)
    assert r.returncode == 2
    assert "collides" in r.stderr


def test_apply_normalizes_crlf_from_blob(project, tmp_path):
    base = turn_base(project)
    edited = base.replace("improved", "improved with\r\nan embedded CRLF")
    r = apply_blob(project, tmp_path, make_blob(edited, turn=1, base=base))
    assert r.returncode == 0, r.stderr
    assert b"\r" not in (project / "doc.md").read_bytes()


def test_apply_rolls_back_when_commit_fails(project, tmp_path):
    base = turn_base(project)
    edited = base.replace("improved", "improved and edited")
    hook = project / ".git" / "hooks" / "pre-commit"
    write_lf(hook, "#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)  # git ignores a hook without the executable bit
    r = apply_blob(project, tmp_path, make_blob(edited, turn=1, base=base))
    assert r.returncode == 2
    # Nothing half-applied: the file is back to the shipped base, the turn
    # is still open, and nothing is staged.
    assert (project / "doc.md").read_text(encoding="utf-8") == base
    state = json.loads((project / ".review" / "state.json").read_text())
    assert state["applied"] is False
    staged = subprocess.run(["git", "-C", str(project), "diff", "--cached", "--name-only"],
                            capture_output=True, text=True).stdout.strip()
    assert staged == ""
    # With the obstacle gone, the same blob applies cleanly.
    hook.unlink()
    r = apply_blob(project, tmp_path, make_blob(edited, turn=1, base=base))
    assert r.returncode == 0, r.stderr


def test_lf_discipline_end_to_end(project):
    # A CRLF file written mid-loop is normalized to LF by agent-commit.
    with open(project / "doc.md", "w", encoding="utf-8", newline="") as f:
        f.write("# Sample\r\n\r\ncrlf paragraph\r\n")
    r = run(["agent-commit", project, "--summary", "CRLF test"])
    assert r.returncode == 0, r.stderr
    raw = (project / "doc.md").read_bytes()
    assert b"\r" not in raw
