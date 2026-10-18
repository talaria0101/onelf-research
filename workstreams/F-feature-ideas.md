# Deep-Dive Research: Forward-Looking Feature Ideas for onelf

**Scope:** Architectural evaluation of 10 candidate features from adjacent fields (containers, OSTree, Landlock, OCI, micro-inits) evaluated against onelf invariants.  
**Core Constraints:** Single executable, static musl runtime, zero host runtime dependencies, unprivileged execution, leaves nothing behind on disk.  
**Evidence Standard:** [verified] (kernel docs/code), [reported] (specifications/benchmarks), [inferred] (architectural deduction).

---

## 1. Candidate Evaluation Matrix

| # | Feature Candidate | Kernel Floor | Privileges | Dev Effort | Constraint Fit | Strategic Verdict |
|:---:|---|:---:|:---:|:---:|:---:|:---:|
| **1** | **Reflink Deduplication (`FICLONERANGE`)** | Linux 4.5+ | Unprivileged | Small | Natural Fit | **Adopt (CLI Tool)** |
| **2** | **Direct Release Delta Updates (Range Requests)** | Linux 3.17+ | Unprivileged | Medium | Natural Fit | **Adopt (High Priority)** |
| **3** | **Embedded Ed25519 Root Signature** | Any Kernel | Unprivileged | Small | Natural Fit | **Adopt (Immediate)** |
| **4** | **Unprivileged Landlock + Seccomp Sandbox** | Linux 5.13+ | Unprivileged | Medium | Natural Fit | **Adopt (Killer Feature)** |
| **5** | **Embedded SBOM & SLSA Provenance** | Any Kernel | Unprivileged | Small | Natural Fit | **Adopt (Enterprise)** |
| **6** | **Service Bundles & Micro-Init Supervisor** | Linux 3.4+ | Unprivileged | Medium | Natural Fit | **Adopt (Major Differentiator)** |
| **7** | **Inspection, Diffing & Audit Tooling** | Any Kernel | Unprivileged | Small-Med | Natural Fit | **Adopt (Quick Win)** |
| **8** | **OCI Registry Distribution (`push`/`pull`)** | Any Kernel | Unprivileged | Medium | Natural Fit | **Adopt (Cloud-Native)** |
| **9** | **Lazy HTTP-Range Streaming Execution** | Linux 4.18+ | Unprivileged | Large | Fragile | **Defer / Experimental** |
| **10**| **Multi-Architecture Universal Fat Bundles** | Linux 3.17+ | Unprivileged | Large | Breaks Philosophy | **Reject** |

---

## 2. Deep-Dive on Top Candidate Features

### 2.1 Direct GitHub Release Delta Updates (HTTP Range on Block Manifest)
- **Mechanism:** Instead of generating and hosting external `.zsync` files, `onelf-rt` fetches the 76-byte footer of the new release via an HTTP Range request (`Range: bytes=-76`), then downloads the compressed manifest. By comparing the new block BLAKE3 hashes against its own local blocks, `onelf-rt` computes the exact missing block ranges and downloads only the changed bytes directly from the GitHub Release asset.
- **Pain Point Exploited:** Eliminates external control files, CI complexity, and zsync bitrot. Maintainers upload **only one file** to GitHub Releases.
- **Effort & Fit:** Medium effort. Perfect fit with `onelf-format` v2/v3 block structure.

### 2.2 Unprivileged Sandboxing via Landlock LSM and Seccomp-BPF
- **Mechanism:** `onelf-rt` parses a declarative `[sandbox]` manifest section. Before calling `execve()` on the entrypoint:
  1. Issues `landlock_create_ruleset()` and `landlock_restrict_self()` (Linux 5.13+) to restrict filesystem read/write access strictly to configured paths.
  2. Compiles a Seccomp-BPF filter to block dangerous syscalls (`TIOCSTI`, `clone3`, `syslog`) or restrict network access (`socket(AF_INET, ...)`).
- **Pain Point Exploited:** Bridges the gap between AppImage (zero sandboxing) and Flatpak (over-sandboxing with portal friction).
- **Effort & Fit:** Medium effort. Operates entirely in unprivileged userspace without root, SUID, or external daemons.

### 2.3 Cryptographic Runtime Integrity via Embedded Ed25519 Root Signature
- **Mechanism:** Embeds a 64-byte Ed25519 signature directly in the trailer or manifest header. The signature covers `package_id` (the BLAKE3 hash of the manifest, which in turn covers `prefix_hash` and all payload block hashes). At startup, `onelf-rt` checks this single 64-byte signature in ~0.2 ms. FUSE verifies individual block hashes on demand.
- **Pain Point Exploited:** Protects binaries against on-disk tampering and malware injection across all filesystems without requiring kernel `fs-verity`.
- **Effort & Fit:** Small effort. Minimal footprint; maximum security impact.

### 2.4 Service Bundles & Micro-Init Supervision
- **Mechanism:** Embeds a micro-init supervisor inside `onelf-rt` using `prctl(PR_SET_CHILD_SUBREAPER, 1)` and `pidfd_open` (Linux 5.3+). Enables packaging multi-process server applications (e.g. Miniflux web app + embedded PostgreSQL database) into a single executable that handles process lifecycle, health checking, signal propagation, and systemd socket activation (`LISTEN_FDS`).
- **Pain Point Exploited:** Solves deployment friction for self-hosted apps without requiring Docker or Kubernetes.
- **Effort & Fit:** Medium effort. Unlocks a completely new category of server-side single-binary applications.
