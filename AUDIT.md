# Fact-Check Audit - 2026-10-18

A verification pass over every workstream in this repository against the
`onelf` source itself ([QaidVoid/onelf](https://github.com/QaidVoid/onelf)).

- **Audited revision:** HEAD `7438f5a` of `QaidVoid/onelf` (342 commits). Note
  that this is one commit past release tag `0.4.1` (tag `0.4.1` = `587f673`;
  the repository tags without a `v` prefix). An earlier edition of these
  documents described `7438f5a` as "tag v0.4.1", which was wrong.
- **Method:** each load-bearing claim was re-checked against the source tree
  (`git grep` over the full history where relevant), the GitHub issue tracker
  (every cited issue/PR number was fetched), and a live smoke test of the
  0.4.1 release binary. Corrections have been applied in place; where a
  correction changed the meaning of a sentence, the new text says what the
  earlier edition got wrong. Where a claim could not be re-verified, its tag
  was downgraded to `[reported]`, `[estimate]`, or `[inferred]`.
- **Workstream F** was spot-checked and needed no changes.

## False conclusions corrected

1. **"onelf relies entirely on host GPU drivers."** False for pinned
   packages. Since v0.4.0, when the host has no usable GL, `onelf-rt` fetches
   the GL build pinned in the recipe over HTTPS and verifies it with BLAKE3
   before use (`launch.rs:410-421`, `platform.rs`; `ONELF_NO_PLATFORM_FETCH`
   disables the path; commits `25abda3`, `275697b`, `f177ff2`).
2. **"Sysroot builds are vulnerable to mirror drift, full stop."** The
   resolver reads the *materialized sysroot image's* local pacman database
   (`closure.rs:22-81`), not live mirror metadata. A recipe can pin the
   `[sysroot]` archive by URL with an enforced BLAKE3 hash
   (`recipe.rs:203-209`), and builds write `.onelf/provenance.toml`
   (commits `8d25a74`, `d04162b`, `275b4a2`). Pinned builds are reproducible;
   the honest residual gap is the absence of a per-package lockfile for
   pinless flows.
3. **"onelf-rt is no_std."** `onelf-rt` is a normal std Rust binary. Only
   `onelf-payloads` (`bootstrap.rs`, `env.rs`) is no_std, and it is
   workspace-excluded.
4. **memfd details.** The fd is named `onelf` (not `onelf-bin`), created with
   flags `0` (no `MFD_CLOEXEC`), and never sealed (`F_ADD_SEALS` appears
   nowhere; no `fchmod` step) (`memfd.rs:16-17`).
5. **"v0.1-era SquashFS experiments."** Fabricated. `git grep` over every
   tree and commit message in the repository's history finds zero occurrences
   of squashfs. `onelf-preload` is 0.2.0-era (added `6977832`), not 0.1-era.
6. **DwarFS flags.** `appimagetool`'s shipping default is
   `-C zstd:level=22 -S26 -B2` (`src/config.rs:175`; tag `0.5.3` and main
   are the same commit, `a9f5ebf`). The first audit pass said
   `appimagetool` uses `-C zstd:level=5 -S19` (`dwarfs.rs:48`); that line
   holds no flags at this revision (it is `return Ok(cached);`), and
   `-C zstd:level=5 -S19` (`dwarfs.rs:149-151`) builds only the throwaway
   OPTIMIZE_LAUNCH profiling image. The comment example with `-B2` is real
   (`dwarfs.rs:104`); `-B6` appears nowhere.
7. **Startup integrity.** The runtime verifies only the XXH32 manifest
   checksum at startup (`loader.rs:61-67`); it does not recompute the
   `package_id` BLAKE3 (that value only names the cache directory). The core
   claim "no at-rest signature" stands.

## Fabricated upstream citations replaced

| Earlier edition cited | Reality |
| --- | --- |
| FreeCAD Issue #960 | #960 is an unrelated stylesheet PR; real evidence is FreeCAD #13182 (fetched, title matches) |
| Flatpak Issue #3184 | unrelated 2019 OpenGL-extension bug; no flatpak issue documents the NVIDIA API-mismatch text |
| shiftkey/desktop #3060 | does not exist; real issue is shiftkey/desktop #591 (fetched) |
| AppImageLauncher #407 in "AppImageCommunity" | the AppImageCommunity org exists but has no AppImageLauncher repo (404); issue lives at TheAssassin/AppImageLauncher #407 (fetched) |
| xdg-desktop-portal #463 | repo moved orgs; correct is flatpak/xdg-desktop-portal #463 (fetched) |

Verified by fetching during this audit: ValveSoftware/Proton #6051,
TheAssassin/AppImageLauncher #407, shiftkey/desktop #591, AppImageKit #1120,
AppImageKit #1078, FreeCAD #13182, flatpak/xdg-desktop-portal #463.
AppImageKit #1078 supports the version-mismatch abort and stack smashing;
the `_rtld_global`/TLS mechanism in the text is inference and is now labeled
as such.

## Citation and detail corrections

- Runtime prefix size: ~1.1 MB slim / ~2.4 MB with updater per the project's
  own docs, confirmed by `onelf pack` output in the smoke test. The earlier
  "1.5-2.0 MB" figure was wrong.
- `.onelf/startup.profile` does not exist; the profile is stored as
  `.onelf/prefetch` (recorded from `ONELF_PROFILE` at pack time).
- Line anchors corrected: `footer.rs` struct at `154-176` (XXH32 at
  `173-175`), `sweep_stale_mountpoints` at `paths.rs:298`, farm
  `materialize()` at `resolve.rs:645-678`, `ONELF_INTERP` handled in
  `onelf-payloads/src/bootstrap.rs:659-673` (the previously cited
  `bootstrap.rs:509-514` is a different site: the `AT_SECURE` gate that
  drops the override for set-id execs), share-file names use an 8-byte
  (16-hex-character) id prefix (`paths.rs:148-161`), NVIDIA handling at
  `set_appdir_env.rs:114-120/455-469/494-520` (not 425), `userland-execve`
  call at `main.rs:482` (not 505), `/etc` to `/KEK` sed at
  `quick-sharun.sh:4902`, DwarFS hotness flag from `dwarfs.rs:99`.
- `quick-sharun.sh` is 170,778 bytes / 5,199 lines. `_lib4bin_collect_ldd`
  (line 1669) is a single `ldd` pass, not recursive; the "strace" sweep is
  `LD_DEBUG=libs` under `STRACE_MODE=1` (`_lib4bin_collect_strace`,
  lines 1728-1815).
- "glibc 2.40 to 2.44" appears nowhere in anylinux; Arch glibc is built with
  `--enable-kernel=4.4` (FAQ.md), so the sharp 2.6.17 floor claim was
  dropped to what the source shows.
- Flatpak has no kernel 3.8 check; the real gate is a bwrap setuid check
  (`flatpak-utils.c:662`). D-Bus proxying is the default, not unconditional
  (`--socket=session-bus` bypasses it). Deploy checkout is at
  `flatpak-dir.c:10134-10168`.
- nix-appimage: pkgforge uses `-b 1M -Xcompression-level 1` (not
  `-no-strip`); upstream `ralismark` avoids `writeClosure`;
  nix-bundle's primary mechanism is `nix-user-chroot` (unshare + chroot),
  not proot; the NixOS warning is at `AppRun.sh:165`; exit code 127 comes
  from `EXIT_EXECERROR` at `main.c:25`, the `exit()` in `die_if` at
  `main.c:40`, and the `unshare` failure site at `main.c:106` (the
  previously cited `main.c:27-33` holds the argv0/appdir/mountroot
  globals).
- `statx` is never used by onelf; kernel floors (3.17/3.8) are now labeled
  inferred from syscall usage. The CLI has 17 subcommands. PR #22 provided
  the determinism groundwork (mtime/SOURCE_DATE_EPOCH, env BTreeMap, sorted
  walks); the runtime `prefix_hash` is part of format v2, not PR #22.
- Latency numbers tagged `[verified]` in the earlier edition were never
  measured; they are now tagged `[estimate]` or `[design target]`. The
  RAM-sharing weakness row now acknowledges same-package sharing via the
  `.share` lease and `setns` (`fuse/share.rs`).
- zsync 0.7.0+ supports HTTPS/HTTP-2; the "no native HTTPS" claim is now
  scoped to the 0.6.x line most distros ship.

## Empirical smoke test (sandbox-limited)

Ran the published 0.4.1 x86_64 Linux release asset
(`onelf-x86_64-linux.tar.xz`, 2,011,044 bytes) in a restricted container:

- `onelf pack` and `onelf info` work as documented; a static hello binary
  packs into a 1,423,306-byte bundle and the pack output confirms
  "Runtime: 1.1 MB".
- The documented 6-rung fallback ladder fired in exactly the documented
  order on a host with all the interesting rungs blocked: memfd skipped
  silently (`memfd_create` returns EPERM under this sandbox's seccomp) and
  the ladder fell through to the FUSE and extraction rungs: FUSE failed
  (no `/dev/fuse`, `fusermount3` exit 1), tmpfs failed ("user namespaces
  are restricted on this host"), rundir failed with EACCES (the sandbox's
  `XDG_RUNTIME_DIR` was empty, so rundir used `/tmp`, which is mounted
  noexec).
- `ONELF_MODE=cache` also failed with EACCES, and `~/.cache/onelf` was
  never created; that failure stays unexplained (the noexec `/tmp` does
  not account for a cache root that was never created).
- `ONELF_MODE=memfd` surfaces `memfd_create: Operation not permitted
  (os error 1)`, matching the code path. These are sandbox limits, not
  onelf defects; the silent memfd fallthrough matches the source.

What the smoke test could not establish: the <1 ms memfd latency claim
(memfd_create is banned here) and any behavior past rundir. Those remain
labeled as design targets in the text.

## Confirmed (highlights)

76-byte footer with all offsets and the XXH32 trailer; 114-byte manifest
header; verdef superset comparison and resolver flow; the 6-rung ladder
order; the full `update.rs` crypto flow (Ed25519 + anti-rollback);
loader patching (`bundle/elf.rs:1070-1087`, including the `/lib64/` ->
`/XXX///` length-preserving rewrite); issues #36 (open), #16, #14 (closed);
PRs #21, #26, #28, #29, #30, #31 merged and #22 merged without the
runtime-hash part; release 0.4.1 published 2026-10-17; the soarpkgs integration is real (the
word "experimental" applied to it is this repo's paraphrase, not soarpkgs'
own wording).

---

# Third pass - 2026-10-19

A second independent re-check of every document, run against `QaidVoid/onelf`
at the same HEAD `7438f5a` (fetched 2026-10-19, unchanged) and fresh clones of
the competitor repos. Two earlier passes had already corrected citations, so
this pass concentrated on claims whose logic, scope or evidence was wrong, and on
onelf features the first edition never read.

**Who checked what.** Five reviewers each took one of workstreams B to F plus
the REPORT/README statements that depend on it. The author of this pass read
workstream A, REPORT.md, README.md and the onelf docs and source. The
reviewers' headline findings that this pass re-ran itself: GitHub release
assets answer `Range: bytes=-76` and a multi-range request with 501 and an
explicit range with 206 (curl, 0.4.1 asset, today); `kernel_compat.rs` is
x86_64-only and switches on below kernel 4.0 or without `statx`;
`.sha256_sig` in `uruntime/src/main.rs:4637-4646`; `footer_hash` patched in
after `package_id` (`pack.rs:1593-1594`); FreeCAD #13182 names `swrast_dri`;
flatpak `flatpak-run.c:2377-2381` (setuid bwrap is supported);
`bubblewrap.c:3447-3452` (cwd kept). The remaining reviewer findings
(Flathub sizes, nix-appimage behaviour, E-document issue summaries) are the
reviewers' own observations and were not re-run here.

## This audit's own earlier claims that were wrong

- "Workstream F was spot-checked and needed no changes." False: F needed 17
  corrections, 6 of them substantive (listed below).
- "The `.share` file name uses the first 8 bytes of the package id" stands for
  the code (`paths.rs:148-153`), but `docs/guide/execution-modes.md` says "whole
  id". The code is right about what happens; the onelf docs page is stale.

## Corrections that change a conclusion

1. **Rank 1 ("unkeyed manifest") was overstated and its fix mis-specified.**
   The source states the hash chain is "an integrity check, not authentication"
   (`footer.rs:195-197`). An in-file signature with an in-file key cannot stop
   a party who can rewrite the file, because that party can replace the runtime
   too. Candidate 3's "tamper-proof" claim is withdrawn. `package_id` also
   excludes the footer (`pack.rs:1528-1594`).
2. **"Zero cross-application sharing" (Rank 7, matrix row 8) was wrong.**
   Dependency sets (0.4.0, `docs/guide/sysroot.md`) share one download, mount,
   server and block cache across packages; cache mode hardlinks identical files
   across packages. The first edition never read either.
3. **Rank 6 item 3 ("onelf does not scrub environment leakage") was wrong.** The
   `onelf-env` constructor hooks `execve`/`posix_spawn` and restores the
   caller's environment for host programs (0.4.0, commit `32cf581`).
4. **Candidate 1 (reflink dedup) cannot work as described.** `FICLONERANGE`
   needs block-aligned offsets; onelf blocks are variable-length zstd output
   with no alignment. Cache-mode CAS already exists.
5. **Candidate 2 (range updates):** GitHub assets reject suffix and multi-range
   requests; onelf already has signed delta updates, so the candidate only
   removes the `.zsync` file and a `.sig` file remains. "Zsync bitrot" applied
   to the C tool, not to `zsync-rs`.
6. **Candidate 6 (micro-init) was presented as new capability.** The onelf docs
   already ship a Miniflux + PostgreSQL single-file example
   (`docs/guide/examples/miniflux.md`) using a shell wrapper.
7. **memfd "win".** It applies to the default entrypoint when it is a static
   binary, the case the project's docs say to ship directly. The "<1 ms" figures
   were never measured and are removed. The "6-rung chain" is 4 modes by
   default for a dynamic app (memfd is static-only, cache is on request).
8. **Rank 3 (compression) is now measured**: DwarFS is 21.3% smaller on
   chromium and firefox trees and 4.0% on dbeaver (`measurements/README.md`).
9. **Anylinux claims:** the 2x-3x and `-S19` DwarFS figures cited a nonexistent
   line 180 of `FAQ.md` (the file has 172 lines); "sub-300 ms" misread "within +/-300 ms
   of native"; "thousands of packages" attached to a documentation repo;
   "glibc 2.40 to 2.6.17" survived in REPORT.md; the 2.6.17 floor is x86_64
   only. Anylinux's own test (2.0 GiB AppImages vs 6.27 GiB Flatpak) is added
   as a reported counter to the Flatpak disk claim.
10. **Flatpak claims:** setuid bwrap is supported; systemd scope fails soft; cwd
    is kept when visible; the 700 MB to 1.5 GB runtime figure is replaced by
    Flathub API sizes (0.67 to 1.09 GB installed, 2026-10-19, reviewer-measured);
    the 15-30 MB delta figure and "millions of installations" had no source.
11. **nix-appimage claims:** "mathematical bit-for-bit", "completely broken",
    2-5x bloat and "exit 127" were unmeasured or true of one of the two
    projects only; several anchors were off (`mkAppImage.nix:48`,
    `AppRun.sh:240`, `main.c:98`).
12. **Smaller:** kernel floors are per mode, not whole-runtime; `/dev/shm`
    appears nowhere in onelf; Landlock network rules need Linux 6.7; `TIOCSTI`
    is an ioctl, not a syscall; micro-init with `pidfd_open` needs 5.3;
    `oci-distribution` is superseded by `oci-client`; `ed25519-compact`, not
    `-dalek`; Rank 9's "glibc 2.31-2.40" has no source; Rank 8 arch list
    re-verified.

## Doc-versus-code disagreements in upstream onelf (for the author)

- `docs/guide/introduction.md` draws 256 KB blocks; the code default is 64 KiB
  (`compress.rs:15`; the file-format reference says 64 KiB).
- `docs/guide/execution-modes.md` names the `.share` record by the whole
  package id; code uses the first 8 bytes (`paths.rs:148-153`).

## New guard

`scripts/check_anchors.py` fails (exit 1) when a cited `file:line` points to a
missing file or past the end of the file. Run against the clones used here it
reports 0 of the 295 anchors in these documents. A planted anchor to line 180 of `FAQ.md`, one to a nonexistent file and one
to line 99999 of ralismark's `main.c` made it exit 1 with all three reported. It does not read
the cited line, so a wrong-but-in-range anchor still passes.

## Not covered

- No launch time, memory or RAM-sharing measurement for any format; the only
  measurement added is size (`measurements/README.md`: one host, one run per
  cell).
- Dependency-set mounts, the pinned-GL fetch and the namespace FUSE rung were
  read, not run; this host's kernel and sandbox were not used to exercise them.
- No Nix, flatpak or ostree binary was available, so Nix image contents,
  byte-reproducibility and Flatpak hardlink checkout were not observed.
- The Ubuntu 24.04 sysctl default, Debian 12 libfuse2 and the NVIDIA mismatch
  text in a Flatpak tracker remain unverified from primary sources (see E).
- Candidate 8's OCI spec wording was not re-checked against the spec text.
- Section 2 matrix cells not named above (for example the nix-appimage
  integrity row beyond the cited lines) were checked only by the reviewers.
- Ranking order in REPORT section 4 is editorial; no frequency data exists.
