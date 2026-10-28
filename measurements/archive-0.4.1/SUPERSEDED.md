# Superseded

These files are the 2026-10-19 size comparison of onelf 0.4.1 against DwarFS
0.15.8. They are kept as the record of that run. Their conclusion, that DwarFS
images are about 21% smaller than onelf packages on chromium and firefox, does
not hold for onelf 0.4.2 with `--payload stipple`. The current numbers are in
`../README.md`.

Host trees were not pinned: on 2026-10-28 `/usr/lib/firefox` and
`/usr/lib/dbeaver` were 241,098 and 542,954 bytes larger than on 2026-10-19,
so cells for those two trees are not comparable across the two runs.
`/usr/lib/chromium` had the identical size (415,421,744 bytes) on both days.
