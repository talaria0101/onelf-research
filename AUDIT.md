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
   nowhere; no `fchmod` step) (`memfd.rs:14-28`).
5. **"v0.1-era SquashFS experiments."** Fabricated. `git grep` over every
   tree and commit message in the repository's history finds zero occurrences
   of squashfs. `onelf-preload` is 0.2.0-era (added `6977832`), not 0.1-era.
6. **DwarFS flags.** `appimagetool` uses `-C zstd:level=5 -S19`
   (`dwarfs.rs:48`). `zstd:level=22 -S26` exists only inside a comment
   example with `-B2` (`dwarfs.rs:104`); `-B6` appears nowhere.
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
| AppImageLauncher #407 in "AppImageCommunity" | org does not exist; issue lives at TheAssassin/AppImageLauncher #407 (fetched) |
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
  `172-175`), `sweep_stale_mountpoints` at `paths.rs:298`, farm
  `materialize()` at `resolve.rs:645-679`, `ONELF_INTERP` handled in
  `onelf-payloads/src/bootstrap.rs:659-673` (the previously cited
  `bootstrap.rs:509-514` does not exist), share-file names use an 8-hex id
  prefix (`paths.rs:148-161`), NVIDIA handling at
  `set_appdir_env.rs:114-120/455-469/494-520` (not 425), `userland-execve`
  call at `main.rs:482` (not 505), `/etc` to `/KEK` sed at
  `quick-sharun.sh:4902`, DwarFS hotness flag from `dwarfs.rs:98`.
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
  from `main.c:27-33`.
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
  silently (`memfd_create` returns EPERM under this sandbox's seccomp),
  FUSE failed (no `/dev/fuse`, `fusermount3` exit 1), tmpfs failed
  ("user namespaces are restricted on this host"), rundir and cache failed
  with EACCES because this sandbox's `/tmp` is mounted noexec.
- `ONELF_MODE=memfd` surfaces `memfd_create: Operation not permitted`,
  matching the code path. These are sandbox limits, not onelf defects; the
  silent memfd fallthrough matches the source.

What the smoke test could not establish: the <1 ms memfd latency claim
(memfd_create is banned here) and any behavior past rundir. Those remain
labeled as design targets in the text.

## Confirmed (highlights)

76-byte footer with all offsets and the XXH32 trailer; 114-byte manifest
header; verdef superset comparison and resolver flow; the 6-rung ladder
order; the full `update.rs` crypto flow (Ed25519 + anti-rollback);
loader patching (`bundle/elf.rs:1073-1090`, including the `/lib64/` ->
`/XXX///` length-preserving rewrite); issues #36 (open), #16, #14 (closed);
PRs #21, #26, #28, #29, #30, #31 merged and #22 merged without the
runtime-hash part; release 0.4.1 published 2026-10-17; the soarpkgs integration is real (the
word "experimental" applied to it is this repo's paraphrase, not soarpkgs'
own wording).
