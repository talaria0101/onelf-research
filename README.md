# onelf Competitive Research & Systems Architecture Report

> **Comprehensive competitive analysis, systems breakdown, ecosystem failure mode audit, and strategic feature roadmap for [onelf](https://github.com/QaidVoid/onelf).**

---

## Navigation & Repository Structure

- **[Master Deliverable: Full Report (REPORT.md)](REPORT.md)**: The complete, dense systems architecture report covering the feature matrix, wins, gaps, 10 evaluated feature candidates, the 3-feature killer roadmap, and open questions for the author.
- **[Workstream A: onelf Internals & Architecture](workstreams/A-onelf-internals.md)**: Deep dive into all crates (`onelf`, `onelf-format`, `onelf-rt`, `onelf-sysroot`, `onelf-payloads`), format v2/v3 layout, 76-byte footer, 6-rung fallback ladder, symbol resolver, self-update, determinism, and 342-commit history.
- **[Workstream B: Anylinux-AppImages & Tooling](workstreams/B-anylinux-appimages.md)**: Analysis of `quick-sharun.sh`, `Anylinux-sharun`, `uruntime`, `cross-libc-dlopen`, glibc 2.40 bundling, in-place dynamic linker patching (`/etc` -> `/KEK`), DwarFS compression, and kernel 2.6.17 syscall emulation.
- **[Workstream C: Flatpak Architecture & Inherent Limits](workstreams/C-flatpak.md)**: Technical breakdown of OSTree CAS hardlinking, runtimes, Bubblewrap sandboxing, Seccomp filters, XDG Desktop Portals, single-file `.flatpak` bundles, and CLI/pipeline failure modes.
- **[Workstream D: nix-appimage & Nix Closures](workstreams/D-nix-appimage.md)**: Analysis of input-addressed closures, two-pass SquashFS layering, `/nix/store` runtime namespace mapping, NixOS host collisions, and unprivileged user namespace crashes.
- **[Workstream E: Linux Portable Packaging Pain Points](workstreams/E-pain-points.md)**: Quantified and ranked matrix of real-world failure modes: the FUSE2 crisis, glibc forward/reverse mismatches, Mesa/NVIDIA driver ABI breaks, Wayland fractional scaling quirks, startup latency, and zsync bitrot.
- **[Workstream F: Forward-Looking Feature Ideas](workstreams/F-feature-ideas.md)**: Rigorous systems evaluation of 10 candidate features: reflink deduplication (`FICLONERANGE`), direct-release range-request updates, embedded Ed25519 root signatures, Landlock/seccomp sandboxing, micro-init supervisors, SBOMs, and OCI distribution.

---

## Executive Summary & Verdict

**`onelf` (v0.4.1, commit `7438f5a`) is the most architecturally elegant single-file executable packaging engine for modern Linux, but it currently occupies an unstable middle ground between minimal runtime agility and enterprise-grade completeness.** 

By fusing a static musl ELF runtime launcher (`onelf-rt`), a zstd block-compressed payload format with 64 KiB BLAKE3 verification (`onelf-format`), and an in-process ELF symbol-version resolver (`verdef.rs`, `resolve.rs`), it achieves what AppImage, Flatpak, and `nix-appimage` cannot: 
1. Sub-millisecond in-memory execution (`memfd_create`) for static payloads with zero filesystem residue.
2. A resilient 6-rung execution fallback ladder that operates even when both FUSE and user namespaces are disabled.
3. Automated host GPU driver discovery without `LD_LIBRARY_PATH` pollution.

However, `onelf` is held back by three critical deficiencies: its manifest integrity is cryptographically unkeyed at rest (relying on an unkeyed XXH32 checksum and detached Ed25519 signatures checked only during updates), it provides zero native sandboxing boundaries against malicious ambient authority, and its sysroot build engine (`onelf-sysroot`) lacks deterministic lockfiles, leaving builds vulnerable to upstream package mirror drift. 

If it formalizes at-rest Merkle tree signatures, in-process Landlock/seccomp sandboxing, and direct-release range-request delta updates, `onelf` will establish an unassailable identity as the premier self-contained application format for Linux.

---

## Quick Comparison Matrix

| Systems Dimension | `onelf` | `Anylinux-AppImages` | `Flatpak` | `nix-appimage` |
| :--- | :--- | :--- | :--- | :--- |
| **Packaging Target** | Single self-contained ELF executable | Single executable AppImage (Type 2/uruntime) | Multi-file deployment into OSTree CAS | Single executable AppImage wrapper |
| **Installation Requirement** | **None** (`chmod +x && ./app`) | **None** (`chmod +x && ./app`) | **Mandatory** (`flatpak install`) | **None** (`chmod +x && ./app`) |
| **In-Memory Exec (`memfd`)** | **Yes (<1 ms)** | No (FUSE mount or `/tmp` extract) | No (bwrap mount namespace) | No (FUSE mount) |
| **Execution Fallback Chain** | **6 rungs** (memfd -> FUSE -> tmpfs -> rundir) | 3 rungs (FUSE -> userns -> extract) | None (fails without daemon/bwrap) | None (crashes if userns disabled) |
| **Host Driver Integration** | In-process symbol-version superset match | Bundled debloated Mesa or `cross-libc-dlopen` | Host-matched runtime extensions | Broken (requires manual nixGL) |
| **Application Sandboxing** | None (ambient user authority) | None (unconfined) | Strict (bwrap + seccomp + portals) | Incidental (path remapping only) |
| **Delta Updates** | Built-in `zsync-rs` (strict HTTPS + Ed25519) | `.zsync` via `appimageupdatetool` | OSTree static binary deltas | None (full re-download) |
| **Startup Latency (Cold)** | **0.5–5 ms** | Sub-300 ms (DwarFS PGO) | 50–200 ms (bwrap + dbus-proxy) | 40–150 ms (FUSE + shell + bwrap) |
| **CLI & Pipeline Transparency** | **100% native** (preserves env/pipes/CWD) | Full transparency (`userland-execve`) | Horrible (mangled paths, env scrubbed) | Functional (minor shell overhead) |
| **Build Reproducibility** | Recipe-based (subject to mirror drift) | Dynamic trace (`quick-sharun.sh`) | Sandboxed manifests (`flatpak-builder`) | **Mathematical bit-for-bit** (`narHash`) |

---

## The Recommended 3-Feature Roadmap

```
THE UNBEATABLE IDENTITY:
┌────────────────────────────────────────────────────────────────────────┐
│ Feature 1: Direct-Release Delta Updates (HTTP Range on Block Manifest) │
│   → Eliminates external .zsync files; maintainers upload ONE binary.   │
├────────────────────────────────────────────────────────────────────────┤
│ Feature 2: Embedded Ed25519 Root Signature for Runtime Integrity       │
│   → Cryptographically anchors updates & verifies binary in <0.2 ms.    │
├────────────────────────────────────────────────────────────────────────┤
│ Feature 3: Native Unprivileged Landlock + Seccomp-BPF Sandboxing       │
│   → In-process containment without Bubblewrap, SUID, or portals.       │
└────────────────────────────────────────────────────────────────────────┘
```

See **[REPORT.md](REPORT.md)** for the complete analysis, citations, and open architectural questions.
