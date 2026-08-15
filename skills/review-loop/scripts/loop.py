#!/usr/bin/env python3
"""review-loop plumbing: git setup, turn state, diffs, blob verification, apply.

Everything mechanical in the loop lives here; SKILL.md drives the agent's
judgement (the editing pass, summaries, comment replies) and calls these
subcommands for state changes. All file IO is UTF-8 with LF newlines.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from collections import namedtuple
from datetime import datetime, timezone
from difflib import SequenceMatcher
from html import escape
from pathlib import Path

AGENT_NAME = "Review-loop agent"
AGENT_EMAIL = "agent@review-loop.local"


def fail(msg):
    print(f"REJECTED: {msg}", file=sys.stderr)
    sys.exit(2)


def read_text(path):
    return Path(path).read_text(encoding="utf-8-sig")


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def to_lf(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text if text.endswith("\n") else text + "\n"


def write_json(path, obj):
    write_text(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- checksum
# FNV-1a 32-bit over UTF-8 bytes; the artifact page implements the same loop.

def fnv1a(text):
    h = 0x811C9DC5
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return format(h, "08x")


# ---------------------------------------------------- markdown block model
# split_blocks / block_kind / normalize are mirrored in template.html; the
# two implementations must stay identical or the round-trip check lies.

# Spelled out rather than \s: the two runtimes disagree on which exotic
# characters that class covers. The separator is the set normalize folds to
# a space and the page's renderer strips, and content must be something
# outside it — a heading that renders empty is an element the serializer
# drops, which fails the page's round-trip check.
HEADING_LINE = re.compile(r"^#{1,6}[ \t\xa0]+[^ \t\xa0]")
LIST_LINE = re.compile(r"^(\s*)([-*]|\d+\.)\s+")


def split_blocks(doc):
    blocks, cur, fence = [], [], False
    for ln in doc.split("\n"):
        stripped = ln.strip()
        if not fence and stripped.startswith("```"):
            if cur:
                blocks.append("\n".join(cur))
                cur = []
            fence = True
            cur.append(ln)
            continue
        if fence:
            cur.append(ln)
            if stripped.startswith("```"):
                fence = False
                blocks.append("\n".join(cur))
                cur = []
            continue
        if stripped == "":
            if cur:
                blocks.append("\n".join(cur))
                cur = []
        elif HEADING_LINE.match(ln):
            # A heading always stands alone, so nothing downstream has to
            # split one back out of a block it shares with body text.
            if cur:
                blocks.append("\n".join(cur))
                cur = []
            blocks.append(ln)
        else:
            cur.append(ln)
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def block_kind(block):
    first = block.split("\n", 1)[0]
    if first.lstrip().startswith("```"):
        return "fence"
    if HEADING_LINE.match(first):
        return "heading"
    if LIST_LINE.match(first):
        return "list"
    return "para"


def collapse(line):
    return re.sub(r"[ \t]+", " ", line).strip()


def normalize(doc):
    # Paragraph-wise whitespace normalization: browser DOM churn (nbsp,
    # soft-wrap joins, doubled spaces) must not masquerade as edits.
    doc = doc.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    out = []
    for b in split_blocks(doc):
        kind = block_kind(b)
        lines = b.split("\n")
        if kind == "fence":
            out.append("\n".join(l.rstrip() for l in lines))
        elif kind == "list":
            # Canonical markers and 2-space nesting; continuation lines merge
            # into their item, so soft-wrap churn is not an edit.
            items = []
            for l in lines:
                c = collapse(l)
                if not c:
                    continue
                m = LIST_LINE.match(l)
                if m:
                    level = len(m.group(1)) // 2
                    marker = "1." if m.group(2)[0].isdigit() else "-"
                    items.append(("  " * level + marker + " " +
                                  collapse(l[m.end():])).rstrip())
                elif items:
                    items[-1] += " " + c
                else:
                    items.append(c)
            out.append("\n".join(items))
        else:
            out.append(collapse(" ".join(lines)))
    return "\n\n".join(out)


# ------------------------------------------------------------- word diffs

def word_tokens(text):
    lead = re.match(r"\s*", text).group(0)
    toks = re.findall(r"\S+\s*", text)
    if lead and toks:
        toks[0] = lead + toks[0]
    elif lead:
        toks = [lead]
    return toks


def word_ops(old, new):
    a, b = word_tokens(old), word_tokens(new)
    # Compare words without their attached whitespace, so a soft-wrap or
    # respace never reads as an edit; equal runs render the new side's text.
    ka = [t.strip() for t in a]
    kb = [t.strip() for t in b]
    ops = []

    def push(op, text):
        if not text:
            return
        if ops and ops[-1][0] == op:
            ops[-1][1] += text
        else:
            ops.append([op, text])

    for tag, i1, i2, j1, j2 in SequenceMatcher(None, ka, kb).get_opcodes():
        if tag == "equal":
            push("eq", "".join(b[j1:j2]))
        else:
            push("del", "".join(a[i1:i2]))
            push("ins", "".join(b[j1:j2]))
    return ops


# -------------------------------------------------------- block alignment
# The agent turn (block_diff) and the human turn (reconstruct) read the same
# alignment, so a changed block has one definition rather than two that drift.

AlignedOp = namedtuple("AlignedOp", "tag old new old_norm new_norm")


def align_blocks(old_doc, new_doc):
    """Match two documents block-wise on their normalized text, yielding one
    AlignedOp per opcode: the raw blocks it covers (what a turn carries)
    alongside the normalized text the match ran on."""
    old, new = split_blocks(old_doc), split_blocks(new_doc)
    old_norm = [normalize(b) for b in old]
    new_norm = [normalize(b) for b in new]
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, old_norm,
                                               new_norm).get_opcodes():
        yield AlignedOp(tag, old[i1:i2], new[j1:j2],
                        old_norm[i1:i2], new_norm[j1:j2])


def block_diff(old_doc, new_doc):
    """Skill-computed diff for changes view: block ops, word ops within
    changed block pairs of the same kind."""
    diff = []
    for op in align_blocks(old_doc, new_doc):
        if op.tag == "equal":
            diff += [{"t": "eq", "md": x} for x in op.new]
        elif op.tag == "delete":
            diff += [{"t": "del", "md": x} for x in op.old]
        elif op.tag == "insert":
            diff += [{"t": "ins", "md": x} for x in op.new]
        else:
            # Pair replaced blocks in order, word-merging only similar
            # heading/para pairs (markers can't break their structure);
            # everything else falls back to del+ins blocks.
            olds, news = op.old, op.new
            k = 0
            while k < min(len(olds), len(news)):
                o, n = olds[k], news[k]
                kind = block_kind(o)
                mergeable = kind == block_kind(n) and kind in ("heading", "para")
                if mergeable and kind == "heading":
                    # A level change rewrites the marker token, and the page
                    # can only re-render a heading whose marker sits in an
                    # equal run — level changes show as del+ins blocks.
                    mergeable = (re.match(r"#+", o).group(0) ==
                                 re.match(r"#+", n).group(0))
                if mergeable:
                    sm = SequenceMatcher(None, op.old_norm[k], op.new_norm[k])
                    if sm.quick_ratio() > 0.5 and sm.ratio() > 0.5:
                        diff.append({"t": "chg", "ops": word_ops(o, n)})
                        k += 1
                        continue
                diff.append({"t": "del", "md": o})
                diff.append({"t": "ins", "md": n})
                k += 1
            diff += [{"t": "del", "md": x} for x in olds[k:]]
            diff += [{"t": "ins", "md": x} for x in news[k:]]
    return diff


def reconstruct(base_doc, returned_doc):
    """The human turn: diff returned markdown against the shipped base.
    Equal-normalized blocks keep the base's raw text (DOM churn is not an
    edit); changed/inserted blocks take the returned text."""
    out = []
    stats = {"changed": 0, "inserted": 0, "deleted": 0}
    for op in align_blocks(base_doc, returned_doc):
        if op.tag == "equal":
            out += op.old
        elif op.tag == "delete":
            stats["deleted"] += len(op.old)
        elif op.tag == "insert":
            out += op.new
            stats["inserted"] += len(op.new)
        else:
            out += op.new
            stats["changed"] += max(len(op.old), len(op.new))
    return "\n\n".join(out) + "\n", stats


# ------------------------------------------------------------ project I/O

def review_dir(project):
    return Path(project) / ".review"


def load_state(project):
    p = review_dir(project) / "state.json"
    if not p.exists():
        fail(f"{project} is not a review-loop project (no .review/state.json) — run init first.")
    return json.loads(read_text(p))


def save_state(project, state):
    write_json(review_dir(project) / "state.json", state)


def load_threads(project):
    p = review_dir(project) / "comments.json"
    if p.exists():
        return json.loads(read_text(p))["threads"]
    return []


def save_threads(project, threads):
    write_json(review_dir(project) / "comments.json", {"threads": threads})


def find_thread(threads, tid):
    return next((t for t in threads if t["id"] == tid), None)


def doc_path(project, state):
    return Path(project) / state["doc"]


def git(project, *args, ident=None):
    env = os.environ.copy()
    if ident:
        name, email = ident
        env.update(GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email,
                   GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email)
    r = subprocess.run(["git", "-C", str(project), *args],
                       env=env, capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def reviewer_ident(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "reviewer"
    return (name, f"{slug}@review-loop.local")


def nearest_existing_dir(path):
    p = Path(path).resolve()
    while not p.is_dir():
        if p.parent == p:
            return p
        p = p.parent
    return p


def inside_repository(path):
    # git's messages are gettext-translated, and the fallback below reads one.
    # git's own test suite pins LANG/LC_ALL to C for that reason; so does this,
    # or a translated locale turns every plain folder into an unreadable answer.
    # Every GIT_* variable goes, not a list of the known-dangerous ones: a
    # ceiling, a redirected GIT_DIR, GIT_OBJECT_DIRECTORY and GIT_COMMON_DIR
    # each hide the repository this probe exists to find, and an allowlist only
    # ever names the ones already discovered. Answering "what is at this path"
    # needs no git configuration at all.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    # The probe states its own git environment rather than inheriting one.
    # Discovery must cross filesystem boundaries: stopping at one hides a
    # repository above a mount, and reports it in a differently worded message
    # that the check below would read as an unrecognized failure — refusing
    # every first init under a mounted home, an external volume or a share.
    env.update(LANG="C", LC_ALL="C", GIT_DISCOVERY_ACROSS_FILESYSTEM="1")
    r = subprocess.run(["git", "-C", str(path), "rev-parse",
                        "--is-inside-work-tree", "--is-inside-git-dir"],
                       env=env, capture_output=True, text=True)
    if r.returncode == 0:
        # A bare repository and a .git directory both answer work-tree=false,
        # so either predicate alone lets one of them through.
        return "true" in r.stdout.split()
    # Exit 128 covers both "no repository here" — the ordinary answer — and a
    # repository git refuses to read (dubious ownership, a .git marker pointing
    # at a missing gitdir). Only the first is a clean no, and only the parenthesis
    # tells them apart: a damaged marker reports "not a git repository: <gitdir>"
    # against the plain folder's "(or any of the parent directories)". Anything
    # unrecognized stops rather than waving init on.
    if "not a git repository (or any of the parent directories)" in r.stderr.lower():
        return False
    fail(f"could not tell whether {path} sits inside a git repository: "
         f"{r.stderr.strip()}")


def is_review_loop_project(project):
    """The re-init exemption. A directory that merely contains a
    .review/state.json is not a project: the state must be readable and name a
    document that is actually here, or a stray or half-written file hands a
    user's own repository to `git add -A`."""
    try:
        state = json.loads(read_text(review_dir(project) / "state.json"))
    except (OSError, ValueError):
        return False
    doc = state.get("doc") if isinstance(state, dict) else None
    return bool(doc) and (project / doc).is_file()


def refuse_nested_project(project):
    """Every turn commits with `git add -A`, so a project pointed at another
    repository's root sweeps that repository's uncommitted work into the
    document's history. An existing review-loop project re-inits normally."""
    if is_review_loop_project(project):
        return
    host = nearest_existing_dir(project)
    if inside_repository(host):
        fail(f"{host} is inside a git repository, so a review-loop project cannot "
             "live there: the loop commits with `git add -A`, which at a "
             "repository's root sweeps that repository's uncommitted work into the "
             "document's history, and below one buries a second repository inside "
             "the first. Nothing was created — pick a folder outside any "
             "repository, e.g. ~/Documents/review-loop/<doc-slug>/.")


# ------------------------------------------------------------ subcommands

def cmd_init(args):
    project = Path(args.project)
    refuse_nested_project(project)  # before anything is created on disk
    project.mkdir(parents=True, exist_ok=True)
    src = Path(args.doc)
    if not src.exists():
        fail(f"document {src} does not exist")
    doc_name = src.name
    dest = project / doc_name
    # samefile, not path equality: a hard link reaches the same bytes under a
    # second name, and opening it for writing truncates the user's original.
    if dest.exists() and dest.samefile(src):
        fail(f"{src} and {dest} are the same file, so importing would rewrite the "
             "original in place rather than copy it. Give the project a folder of "
             "its own, e.g. ~/Documents/review-loop/<doc-slug>/.")
    # Read before touching the destination: a source that cannot be decoded
    # raises here, and a rejected import must leave the project as it found it.
    content = to_lf(read_text(src))
    # Replace the destination entry rather than writing through it: a symlink or
    # a hard link there reaches a file outside the project, and opening it in
    # place would truncate that file. The check above has already refused the one
    # entry that must not be removed — the source itself.
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    write_text(dest, content)

    if not (project / ".git").exists():
        git(project, "init", "-b", "main")
    git(project, "config", "core.autocrlf", "false")
    write_text(project / ".gitattributes", "* -text\n")
    write_text(project / ".gitignore", ".review/\n")

    review_dir(project).mkdir(exist_ok=True)
    save_state(project, {"turn": 0, "applied": True, "doc": doc_name})
    save_threads(project, [])

    ident = reviewer_ident(args.reviewer)
    git(project, "add", "-A", ident=ident)
    git(project, "commit", "-m", f"Import {doc_name} into review loop", ident=ident)
    print(f"Initialized review-loop project at {project} on {doc_name}.")
    print("Next: make the agent pass on the file, then run agent-commit.")


def cmd_agent_commit(args):
    project = Path(args.project)
    state = load_state(project)
    doc = doc_path(project, state)

    content = to_lf(read_text(doc))
    write_text(doc, content)

    prev = git(project, "show", f"HEAD:{state['doc']}")
    if not state["applied"]:
        print(f"note: turn {state['turn']} was never reviewed — this pass supersedes it; "
              "any review of the old turn will be rejected as stale.")

    turn = state["turn"] + 1
    ident = (AGENT_NAME, AGENT_EMAIL)
    git(project, "add", "-A", ident=ident)
    git(project, "commit", "--allow-empty", "-m",
        f"Turn {turn} (agent): {args.summary}", ident=ident)

    rd = review_dir(project)
    checksum = fnv1a(content)
    write_text(rd / "base.md", content)
    write_json(rd / "diff.json", block_diff(prev, content))
    save_state(project, {"turn": turn, "applied": False, "doc": state["doc"],
                         "base_checksum": checksum})
    print(f"Turn {turn} committed and staged as the current base "
          f"(checksum {checksum}).")
    print("Next: build-artifact, then publish .review/artifact.html.")


def cmd_build_artifact(args):
    project = Path(args.project)
    state = load_state(project)
    if state["turn"] == 0:
        fail("no agent turn yet — run agent-commit first.")
    if state["applied"]:
        fail(f"turn {state['turn']}'s review was already applied — the artifact would "
             "show a closed turn that rejects every review sent from it. Take the "
             "next agent pass (agent-commit) first.")
    rd = review_dir(project)
    data = {
        "docName": state["doc"],
        "builtAt": int(datetime.now(timezone.utc).timestamp() * 1000),
        "turn": state["turn"],
        "baseDoc": read_text(rd / "base.md"),
        "checksum": state["base_checksum"],
        "diff": json.loads(read_text(rd / "diff.json")),
        "threads": [t for t in load_threads(project) if not t.get("resolved")],
    }
    template = read_text(Path(__file__).parent / "template.html")
    # Embedding safety: JSON in a data script tag with `<` escaped, so a doc
    # containing </script>, backticks, or quotes cannot break the page.
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    title = escape(state["doc"])
    page = template.replace("__REVIEW_LOOP_DATA__", payload).replace("__DOC_TITLE__", title)
    out = rd / "artifact.html"
    write_text(out, page)
    print(f"Wrote {out}.")
    print("Publish it with the Artifact tool at the SAME file path every turn "
          "(pass the recorded URL from .review/artifact-url.txt when redeploying "
          "from a different session).")


def parse_blob(raw):
    try:
        blob = json.loads(raw)
    except json.JSONDecodeError:
        fail("review blob is not valid JSON — it was likely truncated in transit. "
             "Don't close the artifact tab — send again (use the file download if "
             "pasting keeps truncating).")
    for field in ("turn", "checksum", "baseChecksum", "doc", "comments"):
        if field not in blob:
            fail(f"review blob is missing '{field}' — it was likely truncated in "
                 "transit. Don't close the artifact tab — send again.")
    return blob


def cmd_apply(args):
    project = Path(args.project)
    state = load_state(project)
    rd = review_dir(project)

    # Verify everything before touching anything; a rejection never
    # partially applies.
    blob = parse_blob(read_text(args.blob))

    if blob["turn"] != state["turn"]:
        fail(f"review was built on turn {blob['turn']}, current is {state['turn']} — "
             "refresh the artifact and redo the review on the current turn.")
    if state["applied"]:
        fail(f"turn {state['turn']} review was already applied — a re-send is refused. "
             "Ask for the next agent pass (or reply to threads) instead.")
    if blob["baseChecksum"] != state["base_checksum"]:
        fail("review was built on a different document base than this project's "
             f"turn {state['turn']} — it belongs to another project or document. "
             "Open this document's artifact and redo the review there.")
    if fnv1a(blob["doc"]) != blob["checksum"]:
        fail("review blob checksum does not match its document — it was corrupted "
             "or truncated in transit. Don't close the artifact tab — send again "
             "(use the file download if pasting keeps truncating).")

    base = read_text(rd / "base.md")
    current = read_text(doc_path(project, state))
    if current != base:
        fail(f"the file changed outside the loop since turn {state['turn']} was "
             "published — nothing was applied. Reconcile the file manually, then "
             "run a fresh agent pass.")

    threads = load_threads(project)
    known = {t["id"] for t in threads}
    resolved_ids = blob.get("resolved", [])
    for rid in resolved_ids:
        if rid not in known:
            fail(f"resolve targets unknown thread {rid} — blob malformed; send again.")
    for c in blob["comments"]:
        if not isinstance(c.get("body"), str) or not c["body"].strip():
            fail(f"comment {c.get('id')} has no body — blob malformed; send again.")
        if c.get("reply_to"):
            if c["reply_to"] not in known:
                fail(f"comment {c.get('id')} replies to unknown thread "
                     f"{c['reply_to']} — blob malformed; send again.")
        else:
            if c.get("id") in known:
                fail(f"comment id {c.get('id')} collides with an existing thread — "
                     "blob malformed; send again.")
            a = c.get("anchor") or {}
            if not all(k in a for k in ("text", "occurrence", "before", "after")):
                fail(f"comment {c.get('id')} has an incomplete anchor — blob "
                     "malformed; send again.")
            known.add(c["id"])  # a duplicate later in this same blob collides too

    # All guards passed: apply the human turn. Any non-equal opcode in the
    # reconstruction means a normalized difference, so the stats are the verdict.
    result, stats = reconstruct(base, to_lf(blob["doc"]))
    edited = any(stats.values())
    ident = reviewer_ident(args.reviewer)
    if edited:
        write_text(doc_path(project, state), result)
    detail = (f"{stats['changed']} changed, {stats['inserted']} inserted, "
              f"{stats['deleted']} deleted block(s)" if edited else "comments only")
    try:
        git(project, "add", "-A", ident=ident)
        git(project, "commit", "--allow-empty", "-m",
            f"Turn {state['turn']} (review): {detail}", ident=ident)
    except SystemExit:
        # A failed commit must not leave the review half-applied: restore the
        # shipped base and unstage before surfacing the rejection.
        if edited:
            write_text(doc_path(project, state), base)
        subprocess.run(["git", "-C", str(project), "reset"], capture_output=True)
        raise

    for c in blob["comments"]:
        if c.get("reply_to"):
            t = find_thread(threads, c["reply_to"])
            t["messages"].append({"author": args.reviewer, "body": c["body"]})
            t["pending_reply"] = True
        else:
            threads.append({"id": c["id"], "anchor": c["anchor"], "pending_reply": True,
                            "messages": [{"author": args.reviewer, "body": c["body"]}]})
    for rid in resolved_ids:
        t = find_thread(threads, rid)
        t["resolved"] = True
        t["pending_reply"] = False
    save_threads(project, threads)

    state["applied"] = True
    save_state(project, state)
    write_json(rd / "applied.json",
               {"turn": state["turn"], "reviewer": args.reviewer,
                "applied_at": datetime.now(timezone.utc).isoformat(),
                "blob_checksum": blob["checksum"]})

    print(f"Applied turn {state['turn']} review from {args.reviewer}: {detail}.")
    if resolved_ids:
        print(f"Resolved thread(s): {', '.join(resolved_ids)} — they leave the next turn.")
    pending = [t for t in threads if t.get("pending_reply")]
    if pending:
        print("Threads awaiting an agent reply:")
        for t in pending:
            print(f"  {t['id']}: \"{t['messages'][-1]['body'][:70]}\" "
                  f"(anchored on: \"{t['anchor']['text'][:40]}\")")
        print("Reply to every one (loop.py reply), then take the next agent pass.")
    else:
        print("No comments to answer. Take the next agent pass when asked.")


def cmd_reply(args):
    project = Path(args.project)
    load_state(project)
    threads = load_threads(project)
    t = find_thread(threads, args.thread)
    if t is None:
        fail(f"unknown thread {args.thread} — known: "
             f"{', '.join(x['id'] for x in threads) or '(none)'}")
    t["messages"].append({"author": "agent", "body": args.body})
    t["pending_reply"] = False
    save_threads(project, threads)
    print(f"Replied to {args.thread}. "
          f"{sum(1 for x in threads if x.get('pending_reply'))} still pending.")


def cmd_status(args):
    project = Path(args.project)
    state = load_state(project)
    threads = load_threads(project)
    pending = [t["id"] for t in threads if t.get("pending_reply")]
    print(f"doc: {state['doc']}  turn: {state['turn']}  "
          f"applied: {state['applied']}  threads: {len(threads)}  "
          f"pending replies: {', '.join(pending) or 'none'}")


def main():
    p = argparse.ArgumentParser(prog="loop.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create/prepare a review-loop project")
    s.add_argument("project")
    s.add_argument("--doc", required=True)
    s.add_argument("--reviewer", default="Reviewer")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("agent-commit", help="commit the agent pass and stamp the turn base")
    s.add_argument("project")
    s.add_argument("--summary", required=True)
    s.set_defaults(fn=cmd_agent_commit)

    s = sub.add_parser("build-artifact", help="generate .review/artifact.html for the current turn")
    s.add_argument("project")
    s.set_defaults(fn=cmd_build_artifact)

    s = sub.add_parser("apply", help="verify a review blob and apply it as the human turn")
    s.add_argument("project")
    s.add_argument("--blob", required=True)
    s.add_argument("--reviewer", required=True)
    s.set_defaults(fn=cmd_apply)

    s = sub.add_parser("reply", help="record the agent's reply on a comment thread")
    s.add_argument("project")
    s.add_argument("--thread", required=True)
    s.add_argument("--body", required=True)
    s.set_defaults(fn=cmd_reply)

    s = sub.add_parser("status", help="show turn state")
    s.add_argument("project")
    s.set_defaults(fn=cmd_status)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
