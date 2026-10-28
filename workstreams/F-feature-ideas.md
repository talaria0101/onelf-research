# Deep-Dive Research: Forward-Looking Feature Ideas for onelf

**Scope:** Architectural evaluation of 10 candidate features from adjacent fields (containers, OSTree, Landlock, OCI, micro-inits) evaluated against onelf invariants.  
**Core Constraints:** Single executable, static musl runtime, zero host runtime dependencies, unprivileged execution, leaves nothing behind on disk.  
**Evidence Standard:** [verified] (kernel docs/code), [reported] (specifications/benchmarks), [inferred] (architectural deduction), [estimate] (unmeasured number). The matrix and the four deep-dives below are design proposals: nothing in them exists in onelf at HEAD `cd99efb` (2026-10-26) except where a section says so. Candidate 2 is the one that has since been built (PR #41, unreleased). Kernel floors in the matrix are [verified] against the man7 and kernel.org pages unless a row says [inferred].

---

## 1. Candidate Evaluation Matrix

| # | Feature Candidate | Kernel Floor (beyond onelf baseline) | Privileges | Dev Effort | Constraint Fit | Strategic Verdict |
|:---:|---|:---:|:---:|:---:|:---:|:---:|
| **1** | **Reflink Deduplication (`FICLONERANGE`)** | Linux 4.5+, same filesystem only, and only on reflink-capable filesystems | Unprivileged | Small | Natural Fit | **Adopt (CLI Tool)** |
| **2** | **Direct Release Delta Updates (Range Requests)** | None added | Unprivileged | Medium | Natural Fit | **Built at HEAD (PR #41), unreleased** |
| **3** | **Embedded Ed25519 Root Signature** | None added | Unprivileged | Small | Natural Fit | **Adopt (Immediate)** |
| **4** | **Unprivileged Landlock + Seccomp Sandbox** | Linux 5.13+ (Landlock network rules need 6.7+; Landlock must also be enabled in the kernel build and boot LSM list) | Unprivileged | Medium | Natural Fit | **Adopt (Killer Feature)** |
| **5** | **Embedded SBOM & SLSA Provenance** | None added | Unprivileged | Small | Natural Fit | **Adopt (Enterprise)** |
| **6** | **Service Bundles & Micro-Init Supervisor** | Linux 5.3+ (`pidfd_open`; 3.4+ if only `PR_SET_CHILD_SUBREAPER` and `waitpid` are used) | Unprivileged | Medium | Natural Fit | **Adopt (Major Differentiator)** |
| **7** | **Inspection, Diffing & Audit Tooling** | None added | Unprivileged | Small-Med | Natural Fit | **Adopt (Quick Win)** |
| **8** | **OCI Registry Distribution (`push`/`pull`)** | None added | Unprivileged | Medium | Natural Fit | **Adopt (Cloud-Native)** |
| **9** | **Lazy HTTP-Range Streaming Execution** | Linux 4.18+ [inferred: unprivileged FUSE mounts inside a user namespace] | Unprivileged | Large | Fragile | **Defer / Experimental** |
| **10**| **Multi-Architecture Universal Fat Bundles** | None added | Unprivileged | Large | Breaks Philosophy | **Reject** |

The onelf baseline is Linux 3.17+ (`memfd_create`) and 3.8+ (user namespaces), [inferred] from syscall usage; the repository documents no kernel floor. Section 2 numbers (2.1 to 2.4) do not match matrix numbers: 2.1 is matrix row 2, 2.2 is row 4, 2.3 is row 3, 2.4 is row 6.

---

## 2. Deep-Dive on Top Candidate Features

### 2.1 Direct GitHub Release Delta Updates (HTTP Range on Block Manifest) - built at HEAD, unreleased
- **Status:** Implemented by PR #41 (`cd99efb`, merged 2026-10-26) in `crates/onelf-rt/src/update/{mod,range,delta}.rs` and absent from release 0.4.2, which still uses `zsync-rs`. Read from source and docs only; no HEAD binary was available to run. REPORT.md Candidate 2 has the verified details; this section keeps the design questions this research raised and says how the implementation answered each.
- **Mechanism as built:** the update URL names the release binary. The runtime fetches the 76-byte footer and the compressed manifest with explicit single-range requests, compares block BLAKE3 hashes against the running package's manifest, copies matching blocks from the running binary and fetches the rest. GitHub release assets (`release-assets.githubusercontent.com`) answer a suffix range (`bytes=-76`) and a multi-range request with `501 Unsupported client range` and explicit single ranges with `206` [observed 2026-10-19 and again 2026-10-28, curl, one host, one asset each time], so the implementation sizes the file by `HEAD` (or `Range: bytes=0-0`) and asks for `size-76..size-1` (`range.rs:126-200`, `range.rs:343-430`).
- **The dictionary question this research raised:** reusing a compressed block at a new offset is byte-exact only when the new package uses the same zstd dictionary. The implementation reuses a block only when the dictionaries match and decodes and re-hashes every copied block, so a mismatch downgrades that block to a fetch (`delta.rs:11-15`; `decode_block` is `loader.rs:176-199`). With `--dict` any change to a sampled file changes the dictionary and defeats reuse; `docs/guide/self-update.md` says so and advises leaving `--dict` off.
- **What the first edition did not know:** a compressed stipplefs payload (0.4.2) defeats reuse entirely, because the image retrains its dictionary every build; only `--payload stipple --no-compress` deltas (`delta.rs:16-23`). The smaller package and the delta update are therefore alternatives today.
- **Pain Point Exploited:** The external `.zsync` control file and the `zsyncmake` CI step are gone; publishing is the binary plus `<name>.sig`, or the binary alone under the unsigned opt-in. `zsync` bitrot is a claim about the C `zsync` tool; onelf used `zsync-rs`, and the pain point rested on the extra control file, not on a measured failure.
- **Not measured by anyone here:** real delta sizes for any package, against `zsync` or otherwise.

### 2.2 Unprivileged Sandboxing via Landlock LSM and Seccomp-BPF
- **Mechanism:** `onelf-rt` parses a declarative `[sandbox]` manifest section. Before calling `execve()` on the entrypoint:
  1. Issues `landlock_create_ruleset()` and `landlock_restrict_self()` (Linux 5.13+) to restrict filesystem read/write access strictly to configured paths.
  2. Compiles a Seccomp-BPF filter to block dangerous syscalls (`clone3`, `syslog`), to filter the `TIOCSTI` ioctl request (it is an `ioctl(2)` argument, not a syscall; since Linux 6.2 it may already require `CAP_SYS_ADMIN`), or to restrict network access (`socket(AF_INET, ...)`). Landlock network rules (TCP bind/connect) need ABI v4, Linux 6.7+.
- **Pain Point Exploited:** Bridges the gap between AppImage (no built-in sandboxing) and Flatpak (over-sandboxing with portal friction).
- **Effort & Fit:** Medium effort. Operates entirely in unprivileged userspace without root, SUID, or external daemons. Constraints [inferred]: Landlock and seccomp both require `no_new_privs`, which disables setuid helpers in the launched tree; the filter is inherited by every descendant, so a `clone3` rule should return `ENOSYS` (letting glibc fall back to `clone`) rather than `EPERM` or kill; and in the FUSE rung `onelf-rt` stays resident as the FUSE server, so the restriction must be applied in the child between fork and exec, with the mountpoint allowed. onelf contains no Landlock or seccomp code today (no hits in `crates/`).

### 2.3 Cryptographic Runtime Integrity via Embedded Ed25519 Root Signature
- **Mechanism:** Embeds a 64-byte Ed25519 signature directly in the trailer or manifest header. The signature covers `package_id` (the BLAKE3 hash of the manifest serialized with the `package_id` and `footer_hash` fields zeroed, `pack.rs:1649-1650`; it covers `prefix_hash` and all payload block hashes). It does not cover the footer (flags such as `HOST_LIBS_*`, `MEMFD_HINT`, `EXTERNAL_UPDATER`), because `footer_hash` is patched in after `package_id` is computed (`pack.rs:1719-1720`); a signature must also cover the footer hash or the final manifest bytes. At startup, `onelf-rt` checks this single 64-byte signature in ~0.2 ms [estimate, unmeasured; `openssl speed ed25519` on a Ryzen 7 7700 gave ~14,100 verifies/s, about 0.07 ms, one 2 s run, and that is not the `ed25519-compact` crate onelf uses]. Block hashes are verified on demand wherever blocks are read (FUSE, memfd and extract paths: `loader.rs:94-145`).
- **Current state:** onelf already has Ed25519: a detached signature over the whole file, checked at self-update and by `onelf verify --key --sig` (`verify.rs:139-191`, `sign.rs`). Startup checks only the XXH32 manifest checksum (`loader.rs:67-73`).
- **Pain Point Exploited:** Detects accidental or unsophisticated on-disk modification across all filesystems without requiring kernel `fs-verity`. It does not stop a deliberate attacker who can rewrite the file: the verifier is the runtime inside the same file, and the public key would live in the same file, so the attacker can replace the runtime, the key and the signature together. The repository's own comment says the same of the existing hash chain: "an integrity check, not authentication" (`footer.rs:208-210`). Authentication needs a key the user obtained out of band (pinned by the caller, as `onelf verify --key` does).
- **Effort & Fit:** Small effort. Minimal footprint; maximum security impact.

### 2.4 Service Bundles & Micro-Init Supervision
- **Mechanism:** Embeds a micro-init supervisor inside `onelf-rt` using `prctl(PR_SET_CHILD_SUBREAPER, 1)` (Linux 3.4+) and `pidfd_open` (Linux 5.3+). The memfd rung ends in `execve` and leaves no resident runtime (`memfd.rs`), so a supervisor needs a rung where `onelf-rt` stays as parent. Enables packaging multi-process server applications (e.g. Miniflux web app + embedded PostgreSQL database) into a single executable that handles process lifecycle, health checking, signal propagation, and systemd socket activation (`LISTEN_FDS`).
- **Pain Point Exploited:** Solves deployment friction for self-hosted apps without requiring Docker or Kubernetes.
- **Effort & Fit:** Medium effort. Targets server-side single-binary applications; whether this is a new category is not established here.
