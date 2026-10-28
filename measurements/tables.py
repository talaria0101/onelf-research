#!/usr/bin/env python3
"""Print the markdown tables of measurements/README.md from the raw result files.

Usage: tables.py DIR   (DIR holds size.results.txt, small-trees.results.txt,
extract.results.txt, partial.results.txt, partial2.results.txt)
"""
import os
import re
import statistics
import sys

PREFIX = 1134912  # slim runtime prefix of the 0.4.2 release binary, measured from `onelf info` manifest offset


def sections(path):
    cur, out = None, {}
    for line in open(path):
        m = re.match(r"== (\S+) (?:files=(\d+) )?raw_bytes=(\d+)", line)
        if m:
            cur = m.group(1)
            out[cur] = {"raw": int(m.group(3)), "files": m.group(2), "rows": {}}
            continue
        m = re.match(r"(onelf .*?|mkdwarfs .*?|tar\|zstd -19)(?: rc=(\d+))?(?: secs=([\d.]+))?(?: bytes=(\d+))?$", line.strip())
        if m and cur:
            rc = m.group(2)
            if rc not in (None, "0"):
                print(f"WARNING: rc={rc} for {cur} {m.group(1)}", file=sys.stderr)
            out[cur]["rows"][m.group(1).strip()] = (int(m.group(4)), float(m.group(3)) if m.group(3) else None)
    return out


def pct(a, b):
    return f"{(a / b - 1) * 100:+.1f}%"


def size_table(path, cols):
    data = sections(path)
    print("| Tree | raw | " + " | ".join(c[0] for c in cols) + " |")
    print("|---|---:|" + "---:|" * len(cols))
    for tree, d in data.items():
        cells = []
        for _, key in cols:
            v = d["rows"].get(key)
            cells.append(f"{v[0]:,}" if v else "-")
        print(f"| {tree} | {d['raw']:,} | " + " | ".join(cells) + " |")
    return data


def main():
    d = sys.argv[1]
    cols = [
        ("onelf blocks L19 64K", "onelf blocks L19 64K"),
        ("onelf blocks L19 1M", "onelf blocks L19 1M"),
        ("onelf stipple L19", "onelf stipple L19 default32M"),
        ("onelf stipple L22", "onelf stipple L22 default32M"),
        ("DwarFS L22", "mkdwarfs zstd22 -S26 -B2"),
        ("DwarFS L19", "mkdwarfs zstd19 -S26 -B2"),
        ("tar \\| zstd -19", "tar|zstd -19"),
    ]
    print("### Sizes, three app trees\n")
    big = size_table(os.path.join(d, "size.results.txt"), cols)
    print("\n### Relative to DwarFS L22 (positive = larger than DwarFS)\n")
    print("| Tree | blocks L19 64K | stipple L19 | stipple L19 minus runtime prefix | stipple L19 vs blocks L19 |")
    print("|---|---:|---:|---:|---:|")
    for tree, x in big.items():
        r = x["rows"]
        dw = r["mkdwarfs zstd22 -S26 -B2"][0]
        b = r["onelf blocks L19 64K"][0]
        s = r["onelf stipple L19 default32M"][0]
        print(f"| {tree} | {pct(b, dw)} | {pct(s, dw)} | {pct(s - PREFIX, dw)} | {pct(s, b)} |")
    print("\n### Pack time, seconds (one run per cell, shared host)\n")
    print("| Tree | blocks L19 | stipple L19 | stipple L22 | stipple stored | DwarFS L22 |")
    print("|---|---:|---:|---:|---:|---:|")
    for tree, x in big.items():
        r = x["rows"]
        def t(k):
            return f"{r[k][1]:.1f}"
        print(f"| {tree} | {t('onelf blocks L19 64K')} | {t('onelf stipple L19 default32M')} | {t('onelf stipple L22 default32M')} | {t('onelf stipple store')} | {t('mkdwarfs zstd22 -S26 -B2')} |")
    sm = os.path.join(d, "small-trees.results.txt")
    if os.path.exists(sm):
        print("\n### Smaller trees, onelf bytes with the runtime prefix removed\n")
        print("| Tree | files | raw | blocks L19 | stipple L19 | stipple L19 1M | DwarFS L22 |")
        print("|---|---:|---:|---:|---:|---:|---:|")
        for tree, x in sections(sm).items():
            r = x["rows"]
            def g(k, sub=True):
                v = r.get(k)
                if not v:
                    return "-"
                return f"{v[0] - (PREFIX if k.startswith('onelf') and sub else 0):,}"
            print(f"| {tree} | {x['files']} | {x['raw']:,} | {g('onelf blocks L19 64K')} | {g('onelf stipple L19 default32M')} | {g('onelf stipple L19 1M')} | {g('mkdwarfs zstd22 -S26 -B2')} |")
    for name in ("extract.results.txt", "partial.results.txt", "partial2.results.txt"):
        p = os.path.join(d, name)
        if not os.path.exists(p):
            continue
        groups = {}
        for line in open(p):
            m = re.match(r"(extract|verify|small9|libxul|full) (\S+)(?: bs=(\S+))? (?:rep=\d+ )?rc=(\d+) secs=([\d.]+)", line)
            if m:
                key = " ".join(x for x in (m.group(1), m.group(2), m.group(3)) if x)
                if m.group(4) != "0":
                    print(f"WARNING rc={m.group(4)} {line.strip()}", file=sys.stderr)
                groups.setdefault(key, []).append(float(m.group(5)))
        print(f"\n### {name} (seconds; n, min, median, max)\n")
        print("| case | n | min | median | max |")
        print("|---|---:|---:|---:|---:|")
        for k, v in groups.items():
            print(f"| {k} | {len(v)} | {min(v):.3f} | {statistics.median(v):.3f} | {max(v):.3f} |")


main()
