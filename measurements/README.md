# Package size and decode cost: onelf 0.4.2 vs DwarFS

Question: what do the stipplefs payload (`--payload stipple`, onelf 0.4.2)
and the default blocks payload cost in bytes, in pack time and in decode
time, against a DwarFS image of the same tree? This replaces the 0.4.1
comparison, which is archived in `archive-0.4.1/` and no longer holds for
stipple packages (conclusion there: DwarFS 21% smaller; here a stipple package
is within 0.7% to 1.5% of DwarFS in total bytes on the three large trees).

## What this does not establish

- No FUSE launch was timed. This host has no `/dev/fuse` and no user
  namespaces (`unshare -Ur true`: Operation not permitted), so neither the
  stipplefs mount's start-up path (hot list, background decode, page-cache
  injection) nor onelf's FUSE rung ran. Whether a stipple package starts an
  app faster than a blocks package or a DwarFS AppImage is **not measured
  here**. The only start-up numbers are the stipplefs author's (Blender 5.2,
  first launch 0.73 s against 0.50 s from a plain folder, stipplefs README),
  which are for the stipplefs mount, not onelf, and were not reproduced.
- Decode times below are warm page cache and in-process (`--onelf-extract`,
  `onelf verify`). Cold cache was not possible (`drop_caches` is not writable
  here).
- Delta updates (HEAD only) were not run; see REPORT.md Candidate 2.
- Pack times are one run per cell on a shared host. Load average was 8.9 to
  11.5 while `size.sh` ran (my own `uptime` calls, not in its result file) and
  3.5 to 9.8 at the end of the other scripts (`uptime` lines in their result
  files), so differences under about 20% are not meaningful.

## Conditions

- Date 2026-10-28. One sandbox host, 16 cores, kernel 7.2.11_1, zstd 1.5.7.
- onelf: the 0.4.2 release asset `onelf-x86_64-linux` (7,558,184 bytes, BLAKE3
  `b28375502a8892e3498ba97125585fc31a8cfd008e4cbc6c360de9e674343efd`, matches the
  published `.b3sum`), not built here. It does not contain the HEAD changes
  (delta updates, DRI/GLX farming, multi-entry integration).
- mkdwarfs from the dwarfs 0.15.8 release tarball (Linux x86_64), flags
  `-C zstd:level=22 -S26 -B2` (appimagetool's shipping default, REPORT.md
  Rank 3) and the same with level 19.
- The 0.4.2 slim runtime prefix is 1,134,912 bytes (manifest offset of any
  package built with it; with the updater 2,503,040). onelf byte counts below
  include it unless a column says otherwise. A DwarFS AppImage also carries a
  runtime (uruntime lite v0.8.1, 1,507,016 bytes on 2026-10-19; v0.8.1 was
  still the latest release on 2026-10-28; not re-measured) that these DwarFS
  figures leave out.
- Input trees are directories of the host. `/usr/lib/chromium` was the same size
  as on 2026-10-19 (415,421,744 bytes); `/usr/lib/firefox` and `/usr/lib/dbeaver`
  had grown by 241,098 and 542,954 bytes, so compare formats within this run,
  not against the archived table. Package versions were not recorded.
- onelf options: `pack --command X --level 19` (default 64 KiB blocks) and
  `--payload stipple` (default 32 MiB image blocks). `--block-size` as listed.
- Scripts: `size.sh`, `small-trees.sh`, `extract.sh`, `partial.sh`,
  `partial2.sh`. Raw output: `*.results.txt`. Tables below come from
  `tables.py` run on those files.
- Determinism (`determinism.sh`): two packs of the same input were byte-identical
  (`cmp`) for blocks and for stipple on dbeaver (100 MB) and firefox (312 MB)
  with the same options, three of the 0.4 MB tree per payload, and the firefox and
  dbeaver sizes equal those of the earlier size run to the byte. That is one
  host and one thread count; stipple packing is multi-threaded, so other core
  counts were not tried.

## Sizes (bytes)

| Tree | raw | onelf blocks L19 64K | onelf blocks L19 1M | onelf stipple L19 | onelf stipple L22 | DwarFS L22 | DwarFS L19 | tar \| zstd -19 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| chromium | 415,421,744 | 164,866,025 | 146,758,658 | 130,703,674 | 130,167,098 | 129,797,174 | 133,642,463 | 134,199,070 |
| firefox | 311,841,554 | 106,762,571 | 93,478,087 | 85,100,918 | 84,801,910 | 84,034,685 | 85,427,989 | 85,577,309 |
| dbeaver | 101,513,032 | 91,579,781 | 90,665,731 | 89,180,663 | 89,156,087 | 87,884,176 | 88,057,682 | 88,288,092 |

Relative to DwarFS L22:

| Tree | blocks L19 64K | stipple L19 | stipple L19 minus runtime prefix | stipple L19 vs blocks L19 |
|---|---:|---:|---:|---:|
| chromium | +27.0% | +0.7% | -0.2% | -20.7% |
| firefox | +27.0% | +1.3% | -0.1% | -20.3% |
| dbeaver | +4.2% | +1.5% | +0.2% | -2.6% |

Reading:

- On chromium and firefox the stipple package is 20% to 21% smaller than the
  blocks package and within 0.7% to 1.3% of the DwarFS image, or within 0.2%
  once the runtime prefix is left out. At the same level (19), stipple is
  smaller than DwarFS on chromium (130.70 MB against 133.64 MB) and firefox
  (85.10 MB against 85.43 MB) and larger on dbeaver (89.18 MB against 88.06 MB).
- dbeaver is mostly already-compressed jars. Nothing helps much: stipple saves
  2.6% over blocks and DwarFS is 1.5% smaller than stipple.
- Level 22 over 19 changes stipple by 0.0% to 0.4%. Block size matters a lot:
  firefox stipple L19 is 85.10 MB at 32 MiB blocks and 91.85 MB at 1 MiB.
- Where the gain comes from (inference, not isolated by an experiment): the
  `stored` stipple images are 412,975,418 / 309,639,542 / 102,529,527 bytes
  against raw trees of 415,421,744 / 311,841,554 / 101,513,032, so after removing
  the runtime prefix cross-file chunk dedup saves about 0.9%, 1.1% and 0.1% on
  the three trees (`du -sb` counts directory entries, so the raw sizes are
  slightly high). The 20% gain over blocks therefore comes from compressing
  across files with a large window and, per the source, the x86 branch
  filter, not from dedup. No stipple build with either turned off was made.
- Cost not in the table: a package packed with a compressed stipple payload does
  not delta-update (REPORT.md Candidate 2).

## Smaller trees and many small files (runtime prefix removed from onelf columns)

| Tree | files | raw | blocks L19 | stipple L19 | stipple L19 1M | DwarFS L22 |
|---|---:|---:|---:|---:|---:|---:|
| smoke | 3 | 372,989 | 152,951 | 164,588 | 164,588 | 145,796 |
| zoneinfo | 605 | 569,266 | 249,056 | 148,693 | 148,693 | 109,342 |
| python3.14 | 4320 | 90,898,826 | 25,469,731 | 15,594,973 | 17,524,189 | 14,863,073 |
| icons | 52651 | 141,845,240 | 48,056,645 | 22,339,495 | 24,461,223 | 20,177,318 |

- Stipple's advantage is largest on trees of many small files: `icons`
  (52,651 files) is 53.5% smaller than blocks, `python3.14` 39% smaller.
- DwarFS still wins on those two trees: stipple L19 is 10.7% larger on `icons`
  and 4.9% larger on `python3.14`, so "parity with DwarFS" is a result for
  the two large app trees, not a general one.
- On the 0.4 MB tree (3 files) stipple is 7.6% larger than blocks; on 605
  tiny timezone files it is 40% smaller. The first is one tiny tree, so
  treat it as an observation, not a rule.

## Pack time (seconds)

| Tree | blocks L19 | stipple L19 | stipple L22 | stipple stored | DwarFS L22 |
|---|---:|---:|---:|---:|---:|
| chromium | 81.4 | 35.7 | 73.8 | 6.8 | 48.6 |
| firefox | 61.5 | 35.7 | 56.2 | 2.9 | 47.7 |
| dbeaver | 1.9 | 14.7 | 12.1 | 0.4 | 10.5 |

Stipple packs faster than blocks on chromium (35.7 s against 81.4 s) and
firefox (35.7 s against 61.5 s) and slower on dbeaver (14.7 s against 1.9 s).
Single runs under varying load, with the blocks pack using about one core
(101% CPU observed with `ps` during the chromium pack) and the stipple packer
configured for rayon's thread count (`pack.rs` `stipple_payload`); differences
of that size are plausible but not controlled.

## Decode cost, warm cache, no FUSE (firefox tree, 31 files, 312 MB)

Full extraction and `onelf verify` of the same tree packed three ways
(`x.blocks`, `x.stipple`, `x.stored` in `extract.sh`):

| case | n | min | median | max |
|---|---:|---:|---:|---:|
| extract blocks | 3 | 0.786 | 0.789 | 0.939 |
| extract stipple | 3 | 1.006 | 1.033 | 1.089 |
| extract stored | 3 | 1.059 | 1.071 | 1.095 |
| verify blocks | 3 | 0.780 | 0.788 | 0.807 |
| verify stipple | 3 | 1.114 | 1.125 | 1.145 |
| verify stored | 3 | 1.147 | 1.194 | 1.232 |

Partial extraction of 9 small files (2.56 MB together) and of one 187 MB
file (`libxul.so`), warm:

| case | n | min | median | max |
|---|---:|---:|---:|---:|
| small9 blocks | 5 | 0.010 | 0.011 | 0.012 |
| small9 stipple | 5 | 0.107 | 0.111 | 0.131 |
| small9 stored | 5 | 0.044 | 0.046 | 0.139 |
| libxul blocks | 3 | 0.510 | 0.528 | 0.549 |
| libxul stipple | 3 | 0.745 | 0.749 | 0.874 |
| libxul stored | 3 | 0.740 | 0.748 | 0.859 |

Stipple at smaller image blocks, same 9 small files (packages in `partial2.sh`;
sizes of the firefox tree, 5 reps for the small set, one for the full extract):

| case | n | min | median | max |
|---|---:|---:|---:|---:|
| small9 stipple 1M | 5 | 0.020 | 0.020 | 0.024 |
| small9 stipple 4M | 5 | 0.037 | 0.038 | 0.045 |
| small9 stipple 8M | 5 | 0.054 | 0.055 | 0.059 |
| full stipple 1M | 1 | 0.897 | 0.897 | 0.897 |
| full stipple 4M | 1 | 1.021 | 1.021 | 1.021 |
| full stipple 8M | 1 | 0.951 | 0.951 | 0.951 |

| image block size | package bytes (firefox, L19) | 9 small files, median s |
|---|---:|---:|
| 1 MiB | 91,847,030 | 0.020 |
| 4 MiB | 88,369,526 | 0.038 |
| 8 MiB | 86,997,366 | 0.055 |
| 32 MiB (default) | 85,100,918 | 0.111 |
| blocks 64 KiB (default blocks payload) | 106,762,571 | 0.011 |

Reading:

- Decoding the whole tree is about 30% slower with stipple than with blocks
  (median 1.03 s against 0.79 s); a stored image is no faster, which points at
  the 312 MB of file writes rather than decompression.
- Touching a few small files is about ten times slower with the default 32 MiB
  image block (0.111 s against 0.011 s), because a read of any slice decodes the
  image block that holds it. The cost scales with the image block size.
- This is the cost the stipplefs hot list and background decode are built to
  hide in a FUSE mount, and that mount was not available here. The numbers say
  the decode path itself is not faster than blocks, and they do not say the
  launch path is slower.
