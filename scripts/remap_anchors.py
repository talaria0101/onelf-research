#!/usr/bin/env python3
"""Move cited `file:line` anchors after the cited repository changed.

Usage: remap_anchors.py REPO OLD_REV [--apply] [--apply-bare] [--docs DIR]

REPO is a local git clone (for example a clone of QaidVoid/onelf at HEAD).
OLD_REV is the revision the anchors were last checked against. For every
backticked `path.ext:N` or `path.ext:N-M` in README.md, REPORT.md and
workstreams/*.md (AUDIT.md is a historical record of a past revision and is
never read) whose path names a file that exists in REPO at OLD_REV, the
script takes the cited lines as they were at OLD_REV and looks for the same
lines, contiguous, in the file at the working tree of REPO. Each anchor is
reported as one of

  same      the lines are where they were
  moved     the lines are elsewhere in the same file; the new range is printed
  changed   the lines no longer exist verbatim; a person has to re-read the code
  gone      the file no longer exists at that path
  stale     the doc cites lines OLD_REV does not have (the anchor was already
            wrong, or OLD_REV is not the revision it was checked against)

Whitespace at the end of a line is ignored. Nothing is read from the network.

--apply rewrites `moved` anchors in place when the cited path is qualified
(contains a "/") and names exactly one file at OLD_REV. A bare basename such
as `README.md:44` matches files in many repositories, and the match against
REPO says nothing about which repository the sentence meant, so bare
anchors are only reported unless --apply-bare is also given; with it, a
bare basename is rewritten when exactly one file in REPO has that name.

Exit code 0: nothing needs a person (every anchor same, or moved and
rewritten). Exit code 1: at least one anchor is moved but not rewritten,
changed, gone or stale.
"""
import os
import re
import subprocess
import sys

SPAN = re.compile(r"`([A-Za-z0-9_./-]+\.(?:rs|md|toml|nix|json|py|sh|c|h)):(\d+)(?:-(\d+))?`")


def git(repo, *args):
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed in {repo}: {out.stderr.strip()}")
    return out.stdout


def main():
    argv = sys.argv[1:]
    flags = {a for a in argv if a.startswith("--") and a != "--docs"}
    docs_dir = None
    if "--docs" in argv:
        docs_dir = argv[argv.index("--docs") + 1]
        argv = [a for i, a in enumerate(argv) if a != "--docs" and (i == 0 or argv[i - 1] != "--docs")]
    pos = [a for a in argv if not a.startswith("--")]
    if len(pos) != 2:
        sys.exit(__doc__)
    repo, old = pos
    docs_dir = docs_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    apply_q = "--apply" in flags
    apply_bare = "--apply-bare" in flags

    old_files = git(repo, "ls-tree", "-r", "--name-only", old).splitlines()
    new_files = set(git(repo, "ls-files").splitlines())
    cache = {}

    def lines(rev, path):
        key = (rev, path)
        if key not in cache:
            if rev is None:
                with open(os.path.join(repo, path), encoding="utf-8", errors="replace") as fh:
                    cache[key] = fh.read().split("\n")
            else:
                cache[key] = git(repo, "show", f"{rev}:{path}").split("\n")
        return cache[key]

    docs = [os.path.join(docs_dir, n) for n in ("README.md", "REPORT.md")]
    wdir = os.path.join(docs_dir, "workstreams")
    docs += [os.path.join(wdir, n) for n in sorted(os.listdir(wdir)) if n.endswith(".md")]

    unresolved = 0
    rewritten = 0
    counts = {}
    for doc in docs:
        with open(doc, encoding="utf-8") as fh:
            text = fh.read().split("\n")
        changed_doc = False
        for lineno, line in enumerate(text, 1):
            for m in SPAN.finditer(line):
                cited, a = m.group(1), int(m.group(2))
                b = int(m.group(3) or a)
                cands = [f for f in old_files if f == cited or f.endswith("/" + cited)]
                if not cands:
                    continue
                verdicts = []
                for f in cands:
                    old_lines = lines(old, f)
                    if b > len(old_lines):
                        verdicts.append((f, "stale", None))
                        continue
                    if f not in new_files:
                        verdicts.append((f, "gone", None))
                        continue
                    seg = [x.rstrip() for x in old_lines[a - 1:b]]
                    new_lines = [x.rstrip() for x in lines(None, f)]
                    hits = [i for i in range(len(new_lines) - len(seg) + 1) if new_lines[i:i + len(seg)] == seg]
                    if not hits:
                        verdicts.append((f, "changed", None))
                    elif hits[0] + 1 == a:
                        verdicts.append((f, "same", None))
                    else:
                        verdicts.append((f, "moved", (hits[0] + 1, hits[0] + len(seg))))
                kinds = {v[1] for v in verdicts}
                kind = kinds.pop() if len(kinds) == 1 else "ambiguous"
                counts[kind] = counts.get(kind, 0) + 1
                where = f"{os.path.relpath(doc, docs_dir)}:{lineno} {cited}:{a}-{b}"
                if kind == "same":
                    continue
                qualified = "/" in cited
                unique_old = len(cands) == 1
                unique_bare = unique_old and sum(1 for f in new_files if f == cited or f.endswith("/" + cited)) == 1
                can_apply = (
                    kind == "moved"
                    and unique_old
                    and ((qualified and apply_q) or (not qualified and apply_bare and unique_bare))
                )
                if can_apply:
                    na, nb = verdicts[0][2]
                    old_text = m.group(0)
                    new_text = f"`{cited}:{na}`" if (m.group(3) is None and na == nb) else f"`{cited}:{na}-{nb}`"
                    text[lineno - 1] = text[lineno - 1].replace(old_text, new_text)
                    changed_doc = True
                    rewritten += 1
                    print(f"rewrote {where} -> {na}-{nb}")
                else:
                    unresolved += 1
                    detail = "; ".join(f"{f}: {k}{' ' + str(r) if r else ''}" for f, k, r in verdicts)
                    print(f"{kind.upper()} {where} ({detail})")
        if changed_doc:
            with open(doc, "w", encoding="utf-8") as fh:
                fh.write("\n".join(text))
    print(f"anchors by verdict {counts}; rewritten {rewritten}; needing a person {unresolved}")
    return 1 if unresolved else 0


if __name__ == "__main__":
    sys.exit(main())
