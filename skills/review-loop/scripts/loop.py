#!/usr/bin/env python
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
from datetime import datetime, timezone
from difflib import SequenceMatcher
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
        else:
            cur.append(ln)
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def block_kind(block):
    first = block.split("\n", 1)[0]
    if first.lstrip().startswith("```"):
        return "fence"
    if re.match(r"^#{1,6}\s", first):
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
        elif kind == "heading":
            out.append(collapse(lines[0]))
            rest = collapse(" ".join(lines[1:]))
            if rest:
                out.append(rest)
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


def block_diff(old_doc, new_doc):
    """Skill-computed diff for changes view: block ops, word ops within
    changed block pairs of the same kind."""
    ob, nb = split_blocks(old_doc), split_blocks(new_doc)
    on = [normalize(x) for x in ob]
    nn = [normalize(x) for x in nb]
    diff = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, on, nn).get_opcodes():
        if tag == "equal":
            diff += [{"t": "eq", "md": x} for x in nb[j1:j2]]
        elif tag == "delete":
            diff += [{"t": "del", "md": x} for x in ob[i1:i2]]
        elif tag == "insert":
            diff += [{"t": "ins", "md": x} for x in nb[j1:j2]]
        else:
            # Pair replaced blocks in order, word-merging only similar
            # heading/para pairs (markers can't break their structure);
            # everything else falls back to del+ins blocks.
            olds, news = ob[i1:i2], nb[j1:j2]
            k = 0
            while k < min(len(olds), len(news)):
                o, n = olds[k], news[k]
                if (block_kind(o) == block_kind(n)
                        and block_kind(o) in ("heading", "para")
                        and SequenceMatcher(None, normalize(o), normalize(n)).ratio() > 0.5):
                    diff.append({"t": "chg", "ops": word_ops(o, n)})
                else:
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
    bb, rb = split_blocks(base_doc), split_blocks(returned_doc)
    bn = [normalize(x) for x in bb]
    rn = [normalize(x) for x in rb]
    out = []
    stats = {"changed": 0, "inserted": 0, "deleted": 0}
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, bn, rn).get_opcodes():
        if tag == "equal":
            out += bb[i1:i2]
        elif tag == "delete":
            stats["deleted"] += i2 - i1
        elif tag == "insert":
            out += rb[j1:j2]
            stats["inserted"] += j2 - j1
        else:
            out += rb[j1:j2]
            stats["changed"] += max(i2 - i1, j2 - j1)
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
    write_text(review_dir(project) / "state.json", json.dumps(state, indent=2) + "\n")


def load_threads(project):
    p = review_dir(project) / "comments.json"
    if p.exists():
        return json.loads(read_text(p))["threads"]
    return []


def save_threads(project, threads):
    write_text(review_dir(project) / "comments.json",
               json.dumps({"threads": threads}, indent=2, ensure_ascii=False) + "\n")


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


# ------------------------------------------------------------ subcommands

def cmd_init(args):
    project = Path(args.project)
    project.mkdir(parents=True, exist_ok=True)
    src = Path(args.doc)
    if not src.exists():
        fail(f"document {src} does not exist")
    doc_name = src.name
    content = read_text(src).replace("\r\n", "\n").replace("\r", "\n")
    if not content.endswith("\n"):
        content += "\n"
    write_text(project / doc_name, content)

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

    content = read_text(doc).replace("\r\n", "\n").replace("\r", "\n")
    if not content.endswith("\n"):
        content += "\n"
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
    write_text(rd / "base.md", content)
    write_text(rd / "diff.json",
               json.dumps(block_diff(prev, content), ensure_ascii=False) + "\n")
    write_text(rd / "turn.json", json.dumps(
        {"turn": turn, "summary": args.summary, "questions": args.questions or []},
        indent=2, ensure_ascii=False) + "\n")
    save_state(project, {"turn": turn, "applied": False, "doc": state["doc"],
                         "base_checksum": fnv1a(content)})
    print(f"Turn {turn} committed and staged as the current base "
          f"(checksum {fnv1a(content)}).")
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
    meta = json.loads(read_text(rd / "turn.json"))
    data = {
        "docName": state["doc"],
        "builtAt": int(datetime.now(timezone.utc).timestamp() * 1000),
        "turn": state["turn"],
        "summary": meta["summary"],
        "questions": meta["questions"],
        "baseDoc": read_text(rd / "base.md"),
        "checksum": state["base_checksum"],
        "diff": json.loads(read_text(rd / "diff.json")),
        "threads": [t for t in load_threads(project) if not t.get("resolved")],
    }
    template = read_text(Path(__file__).parent / "template.html")
    # Embedding safety: JSON in a data script tag with `<` escaped, so a doc
    # containing </script>, backticks, or quotes cannot break the page.
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    title = state["doc"].replace("&", "&amp;").replace("<", "&lt;")
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
    for field in ("turn", "checksum", "doc", "comments"):
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
            a = c.get("anchor") or {}
            if not all(k in a for k in ("text", "occurrence", "before", "after")):
                fail(f"comment {c.get('id')} has an incomplete anchor — blob "
                     "malformed; send again.")

    # All guards passed: apply the human turn.
    result, stats = reconstruct(base, blob["doc"])
    edited = normalize(result) != normalize(base)
    ident = reviewer_ident(args.reviewer)
    if edited:
        write_text(doc_path(project, state), result)
    detail = (f"{stats['changed']} changed, {stats['inserted']} inserted, "
              f"{stats['deleted']} deleted block(s)" if edited else "comments only")
    git(project, "add", "-A", ident=ident)
    git(project, "commit", "--allow-empty", "-m",
        f"Turn {state['turn']} (review): {detail}", ident=ident)

    new_threads = []
    for c in blob["comments"]:
        if c.get("reply_to"):
            t = next(t for t in threads if t["id"] == c["reply_to"])
            t["messages"].append({"author": args.reviewer, "body": c["body"]})
            t["pending_reply"] = True
        else:
            threads.append({"id": c["id"], "anchor": c["anchor"], "pending_reply": True,
                            "messages": [{"author": args.reviewer, "body": c["body"]}]})
            new_threads.append(c["id"])
    for rid in resolved_ids:
        t = next(t for t in threads if t["id"] == rid)
        t["resolved"] = True
        t["pending_reply"] = False
    save_threads(project, threads)

    state["applied"] = True
    save_state(project, state)
    write_text(rd / "applied.json", json.dumps(
        {"turn": state["turn"], "reviewer": args.reviewer,
         "applied_at": datetime.now(timezone.utc).isoformat(),
         "blob_checksum": blob["checksum"]}, indent=2) + "\n")

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
    t = next((t for t in threads if t["id"] == args.thread), None)
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
    s.add_argument("--questions", action="append")
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
