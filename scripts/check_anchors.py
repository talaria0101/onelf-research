#!/usr/bin/env python3
"""Check file:line anchors cited in the markdown files against upstream clones.

Usage: check_anchors.py ROOT[=ALIAS] [ROOT[=ALIAS] ...]

Each ROOT is a local clone of a repository this research cites. A cited path
whose first component equals a ROOT's directory name or its ALIAS (for
example `ralismark/main.c`) is looked up in that clone only. For every
backticked `path.ext:N` or `path.ext:N-M` in README.md, REPORT.md, AUDIT.md
and workstreams/*.md, the script looks for files in the ROOTs whose path ends
with the cited path. An anchor is reported when

  * no file ends with the cited path, or
  * every matching file is shorter than the cited line number.

A bare basename such as `main.rs` matches many files, so a pass means "some
candidate is long enough", not "the line says what the text claims". It
catches wrong files and line numbers past the end of the file (for example
`FAQ.md:180` against a 172-line file). It does not read the line.
Exit code 0: no anchor reported. Exit code 1: at least one reported.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SPAN = re.compile(r"`([A-Za-z0-9_./-]+\.(?:rs|md|sh|c|h|nix|toml|json|py|hook)):(\d+)(?:-(\d+))?`")


def tracked_files(root):
    out = subprocess.run(["git", "-C", root, "ls-files"], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"not a git clone: {root}")
    return out.stdout.splitlines()


def line_count(path):
    with open(path, "rb") as fh:
        return sum(1 for _ in fh)


def main():
    roots = sys.argv[1:]
    if not roots:
        sys.exit(__doc__)
    index = []
    names = {}
    for spec in roots:
        root, _, alias = spec.partition("=")
        root = root.rstrip("/")
        for name in {os.path.basename(root), alias} - {""}:
            names[name] = root
        for rel in tracked_files(root):
            index.append((root, rel, os.path.join(root, rel)))
    docs = [os.path.join(REPO, n) for n in ("README.md", "REPORT.md", "AUDIT.md")]
    wdir = os.path.join(REPO, "workstreams")
    docs += [os.path.join(wdir, n) for n in sorted(os.listdir(wdir)) if n.endswith(".md")]
    lengths = {}
    bad = 0
    checked = 0
    for doc in docs:
        with open(doc, encoding="utf-8") as fh:
            for lineno, text in enumerate(fh, 1):
                for m in SPAN.finditer(text):
                    cited, a, b = m.group(1), int(m.group(2)), m.group(3)
                    need = int(b) if b else a
                    head, _, tail = cited.partition("/")
                    if tail and head in names:
                        only, want = names[head], tail
                    else:
                        only, want = None, cited
                    cands = [
                        full
                        for root, rel, full in index
                        if (only is None or root == only) and (rel == want or rel.endswith("/" + want))
                    ]
                    checked += 1
                    name = os.path.relpath(doc, REPO)
                    if not cands:
                        print(f"{name}:{lineno}: no file ends with {cited}")
                        bad += 1
                        continue
                    for c in cands:
                        if c not in lengths:
                            lengths[c] = line_count(c)
                    if all(lengths[c] < need for c in cands):
                        longest = max(lengths[c] for c in cands)
                        print(f"{name}:{lineno}: {cited}:{need} is past the end (longest match has {longest} lines)")
                        bad += 1
    print(f"checked {checked} anchors, reported {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
