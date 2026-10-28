# onelf Competitive Research & Systems Architecture Report

> **Comprehensive competitive analysis, systems breakdown, ecosystem failure mode audit, and strategic feature roadmap for [onelf](https://github.com/QaidVoid/onelf).**

---

## Navigation & Repository Structure

- **[Master Deliverable: Full Report (REPORT.md)](REPORT.md)**: The complete, dense systems architecture report covering the feature matrix, wins, gaps, 10 evaluated feature candidates, the 3-feature killer roadmap, and open questions for the author.
- **[Fact-Check Audit (AUDIT.md)](AUDIT.md)**: The 2026-10-18 and 2026-10-19 verification passes against `onelf` at `7438f5a`, and the 2026-10-28 update pass against HEAD `cd99efb` (release 0.4.2): which claims held, which went stale, and what was corrected in place.
- **[Measurements](measurements/README.md)**: The measured comparison in this repo: package size and pack time of onelf 0.4.2 (default blocks payload and the stipplefs payload) against DwarFS on three app trees, plus warm extract time. Scripts and raw output. The 0.4.1 numbers are kept under `measurements/archive-0.4.1/` and are superseded.
- **[Anchor checker](scripts/check_anchors.py)**: Checks every cited `file:line` against local clones of the upstream repos; run it after editing citations.
- **[Anchor remapper](scripts/remap_anchors.py)**: After a cited repo changes, finds where each cited line range went (`same`, `moved`, `changed`, `gone`) and rewrites path-qualified moves on request.
- **[Workstream A: onelf Internals & Architecture](workstreams/A-onelf-internals.md)**: Deep dive into all crates (`onelf`, `onelf-format`, `onelf-rt`, `onelf-sysroot`, `onelf-payloads`), format v2/v3 layout, 76-byte footer, 6-rung fallback ladder, symbol resolver, self-update, determinism, and 351-commit history.
- **[Workstream B: Anylinux-AppImages & Tooling](workstreams/B-anylinux-appimages.md)**: Analysis of `quick-sharun.sh`, `Anylinux-sharun`, `uruntime`, `cross-libc-dlopen`, glibc bundling, in-place dynamic linker patching (`/etc` -> `/KEK`), DwarFS compression, and the x86_64-only kernel 2.6.17 syscall emulation.
- **[Workstream C: Flatpak Architecture & Inherent Limits](workstreams/C-flatpak.md)**: Technical breakdown of OSTree CAS hardlinking, runtimes, Bubblewrap sandboxing, Seccomp filters, XDG Desktop Portals, single-file `.flatpak` bundles, and CLI/pipeline failure modes.
- **[Workstream D: nix-appimage & Nix Closures](workstreams/D-nix-appimage.md)**: Analysis of input-addressed closures, two-pass SquashFS layering, `/nix/store` runtime namespace mapping, NixOS host collisions, and unprivileged user namespace crashes.
- **[Workstream E: Linux Portable Packaging Pain Points](workstreams/E-pain-points.md)**: Ranked (editorially, not measured) matrix of cited failure modes: the FUSE2 crisis, glibc forward/reverse mismatches, Mesa/NVIDIA driver ABI breaks, Wayland fractional scaling quirks, startup latency (no measured figures), and the original zsync client's lack of HTTPS.
- **[Workstream F: Forward-Looking Feature Ideas](workstreams/F-feature-ideas.md)**: Evaluation of 10 candidate features (design proposals, not findings): reflink deduplication (`FICLONERANGE`), direct-release range-request updates, embedded Ed25519 root signatures, Landlock/seccomp sandboxing, micro-init supervisors, SBOMs, and OCI distribution.

---

## Executive Summary & Verdict

**`onelf` (latest release 0.4.2, 2026-10-21; source audited at HEAD `cd99efb`, 2026-10-26, four unreleased commits later) is a young (351 commits), technically careful single-file executable packaging engine for modern Linux. "Most elegant" is an opinion and this report does not measure it.** 

By fusing a static musl ELF runtime launcher (`onelf-rt`), a payload that is either independent zstd blocks (default) or, since 0.4.2, a deduplicating stipplefs image (`--payload stipple`), with 64 KiB BLAKE3 verification in both (`onelf-format`), and an in-process ELF symbol-version resolver (`verdef.rs`, `resolve.rs`), it combines three things that no single competitor combines (Anylinux-AppImages also shares mounts and has a fallback chain, so none is unique alone): 
1. In-memory execution (`memfd_create`) for static single-binary packages only, with zero filesystem residue. The project's own docs say to ship such a binary directly, and no latency has been measured.
2. A six-mode execution ladder whose last mode (persistent cache) is opt-in. It still runs with FUSE and user namespaces both unavailable, if a writable directory on an exec-capable mount exists.
3. Automated host GPU driver discovery without `LD_LIBRARY_PATH` pollution, plus (since v0.4.0) an automatic fetch of the recipe's pinned GL build when the host has none.

Three limits stand out: nothing in the file authenticates its producer at launch (the hash chain is unkeyed by design and the source says so, `footer.rs:208-210`; the detached Ed25519 signature is checked on self-update and by `onelf verify --key --sig`), it has no sandbox (a stated non-goal in `docs/guide/introduction.md`), and its sysroot builds are only reproducible when the recipe pins the sysroot archive by BLAKE3 hash (supported since v0.4.0, with provenance in `.onelf/provenance.toml`); unpinned recipes drift with upstream images. 

Since the previous edition: the size gap to DwarFS closed with the stipple payload (measured: the stipple package is 0.7% to 1.5% larger than a DwarFS image of the same tree in total bytes, and 20% smaller than the default blocks package on chromium and firefox; `measurements/README.md`), and the range-request delta update that REPORT.md section 6 proposed is built at HEAD (PR #41, unreleased, read from source and not run). REPORT.md section 6 still proposes launch-time signature checking and in-process sandboxing; they are design proposals, and whether they would make onelf the premier format is not something this report can show.

---

## Quick Comparison Matrix

| Systems Dimension | `onelf` | `Anylinux-AppImages` | `Flatpak` | `nix-appimage` |
| :--- | :--- | :--- | :--- | :--- |
| **Packaging Target** | Single self-contained ELF executable | Single executable AppImage (Type 2/uruntime) | Multi-file deployment into OSTree CAS | Single executable AppImage wrapper |
| **Installation Requirement** | **None** (`chmod +x && ./app`) | **None** (`chmod +x && ./app`) | **Mandatory** (`flatpak install`) | **None** (`chmod +x && ./app`) |
| **In-Memory Exec (`memfd`)** | **Yes** (static single binaries only; latency not measured) | No (FUSE mount or `/tmp` extract) | No (bwrap mount namespace) | No (FUSE mount) |
| **Execution Fallback Chain** | **6 modes** (memfd -> userns FUSE -> fusermount3 -> tmpfs -> rundir -> cache); memfd is static-only and cache is on request, or first with `--prefer-cache` (0.4.2) | 3 rungs (FUSE -> userns -> extract, extraction capped at 350 MiB) | None (needs bwrap, setuid or userns) | None for the userns/bwrap step (ralismark exits 127; pkgforge's wrapper exits 0) |
| **Host Driver Integration** | In-process symbol-version superset match + pinned-GL fetch | Bundled debloated Mesa or `cross-libc-dlopen` | Host-matched runtime extensions | OpenGL off NixOS is a documented known problem (README suggests nixGL) |
| **Application Sandboxing** | None (stated non-goal) | None (unconfined) | bwrap + seccomp + portals, as tight as the app's permissions | Incidental (path remapping only) |
| **Delta Updates** | 0.4.2: built-in `zsync-rs` (needs `.zsync` + `.zsync.sig`). HEAD, unreleased: direct-release range requests, binary + `.sig` only (strict HTTPS, Ed25519 or explicit unsigned opt-in); a compressed stipple payload does not delta | `.zsync` via `appimageupdatetool` (opt-in hook) | OSTree static binary deltas | None found [absence inferred] |
| **Package Size (same tree, measured)** | Blocks payload: 27% over DwarFS on chromium and firefox, 4% on dbeaver. `--payload stipple` (0.4.2): 0.7% to 1.5% over; DwarFS still ahead by 5% to 11% on small-file trees (icons, python; onelf runtime prefix excluded) | DwarFS L22 `-S26 -B2` is the baseline (plus its runtime, ~1.5 MB) | OSTree stores files uncompressed on disk | SquashFS; not measured |
| **Startup Latency (Cold)** | Not measured here. Author-reported for the stipplefs mount: Blender first launch 0.73 s vs 0.50 s plain folder. Warm decode without FUSE was not faster with stipple (`measurements/README.md`) | Upstream: within +/-300 ms of native on a 2016 CPU [reported] | 50-200 ms [estimate, unmeasured] | 40-150 ms [estimate, unmeasured] |
| **CLI & Pipeline Transparency** | Preserves stdin/stdout, signals, cwd; restores the caller's environment for host programs the app starts | `userland-execve` for dynamic 64-bit binaries; `anylinux.so` scrubs child environments | Friction: fixed env blocklist, cwd kept only if visible in the sandbox | Functional (shell overhead unmeasured) |
| **Build Reproducibility** | Recipe-based; reproducible with a pinned sysroot archive (BLAKE3-enforced), drifts unpinned | Dynamic trace (`quick-sharun.sh`) | Sandboxed manifests (`flatpak-builder`) | Inputs pinned by `flake.lock`; byte-identical output not measured |

---

## The Recommended 3-Feature Roadmap

```
THE UNBEATABLE IDENTITY:
┌────────────────────────────────────────────────────────────────────────┐
│ Feature 1: Direct-Release Delta Updates (HTTP Range on Block Manifest) │
│   → BUILT at HEAD (PR #41), unreleased; needs measurement + release.   │
├────────────────────────────────────────────────────────────────────────┤
│ Feature 2: Embedded Ed25519 Root Signature for Runtime Integrity       │
│   → Detects modification at launch (not authentication; see Cand. 3). │
├────────────────────────────────────────────────────────────────────────┤
│ Feature 3: Native Unprivileged Landlock + Seccomp-BPF Sandboxing       │
│   → Landlock/seccomp confinement without Bubblewrap or portals.        │
└────────────────────────────────────────────────────────────────────────┘
```

See **[REPORT.md](REPORT.md)** for the complete analysis, citations, and open architectural questions, and **[AUDIT.md](AUDIT.md)** for what the 2026-10-18 fact-check changed.
