# Compression size: onelf vs DwarFS

Question: how much larger is an onelf package than a DwarFS image of the same
tree? (REPORT.md, Rank 3.) Sizes only. No launch time, read speed or memory
was measured, so nothing here says which format starts an app faster.

## Conditions

- Date 2026-10-19. One sandbox host, 16 cores, kernel 7.2.11_1, zstd 1.5.7.
- onelf 0.4.1 release binary (`onelf-x86_64-linux.tar.xz`, as shipped).
- mkdwarfs from the dwarfs 0.15.8 release tarball (Linux x86_64).
- Input trees: `/usr/lib/chromium`, `/usr/lib/firefox`, `/usr/lib/dbeaver` of the
  host. Their package versions were not recorded.
- One run per cell. Output sizes are bytes. No repeat was made, so run-to-run
  variation is unknown (compression is expected to be deterministic).
- DwarFS flags `-C zstd:level=22 -S26 -B2` are appimagetool's shipping default
  (`config.rs:175`); `-C zstd:level=19 -S26 -B2` matches onelf's default level.
  onelf `pack` default is `--level 19`, 64 KiB blocks, no dictionary.
- The onelf size includes the 1.1 MB runtime prefix; the DwarFS image has none.
- Scripts and raw output: `compression-size.sh`, `compression-size.results.txt`,
  `compression-size-blocksize.sh`, `compression-size-blocksize.results.txt`.

## Results (bytes; raw = `du -sb` of the tree)

| Tree | raw | onelf L19 | onelf L22 | onelf L19 + dict | DwarFS L22 | DwarFS L19 | tar \| zstd -19 |
|---|---:|---:|---:|---:|---:|---:|---:|
| chromium | 415,421,744 | 164,845,553 | 164,834,290 | 161,989,820 | 129,797,179 | 133,642,461 | 134,199,070 |
| firefox | 311,600,456 | 106,495,176 | 106,486,519 | 104,099,159 | 83,807,831 | 85,196,451 | 85,382,003 |
| dbeaver | 100,970,078 | 91,067,054 | 91,066,743 | 90,483,061 | 87,387,760 | 87,552,354 | 87,793,286 |

DwarFS (shipping flags) is 21.3% smaller than onelf default on chromium, 21.3%
on firefox and 4.0% on dbeaver (mostly already-compressed jars).

onelf block size on chromium (level 19):

| `--block-size` | bytes | vs 64 KiB |
|---:|---:|---:|
| 65,536 (default) | 164,845,553 | 0% |
| 262,144 | 154,118,704 | 6.5% smaller |
| 1,048,576 | 146,738,186 | 11.0% smaller |
| 4,194,304 | 141,702,303 | 14.0% smaller |

## Reading

- The gap is real on these trees and is mostly the block window, not the
  compressor level: raising onelf from level 19 to 22 changes nothing
  (under 0.01%), while a plain solid `tar | zstd -19` lands within 1% of
  DwarFS.
- The project documents the trade: smaller blocks start apps faster from a cold
  cache at a size cost (`docs/reference/recipe-schema.md:100-104`: on Blender,
  64 KiB vs 256 KiB, 17% faster for a 5% larger package). This host's chromium
  tree shows 64 KiB costing 7.0% over 256 KiB, in line with that.
- Not established: whether the size difference matters to users, and how each
  format's startup compares on these trees.
