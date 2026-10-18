# Deep-Dive Technical Research Report: onelf Internal Architecture

**Target Repository:** `QaidVoid/onelf` (https://github.com/QaidVoid/onelf)  
**Analyzed Commits:** 342 commits; audited at HEAD `7438f5a`, which is one commit past tag `0.4.1` (the repo tags releases without a `v` prefix; `0.4.1` points at `587f673`)  
**Crates Analyzed:** `onelf`, `onelf-format`, `onelf-rt`, `onelf-sysroot`, `onelf-payloads` (and former `onelf-preload`)  
**Evidence Standard:** Every factual claim is marked as `[verified]` (observed directly in code/docs), `[reported]` (stated in GitHub PR/issue/commit messages), or `[inferred]` (derived through technical deduction).

---

## 1. Binary Format and Manifest Schema

### 1.1 Physical File Layout & Alignment
An `onelf` executable is a contiguous, self-contained ELF executable container consisting of up to five concatenated sections (`docs/reference/file-format.md:8-28` `[verified]`):

```text
┌────────────────────────────────────────────────────────┐  Offset 0
│ Runtime Prefix (Static Musl ELF, slim or update build) │
├────────────────────────────────────────────────────────┤  Offset: footer.manifest_offset
│ Manifest (zstd-compressed)                             │
│   ├── Manifest Header (114 bytes in version 3)         │
│   ├── Entrypoints (14 bytes * entrypoint_count)        │
│   ├── Entries (Variable size * entry_count)            │
│   ├── Lib Dir Offsets (4 bytes * lib_dir_count)        │
│   └── String Table (null-terminated strings)           │
├────────────────────────────────────────────────────────┤  Offset: footer.payload_offset
│ Payload Section                                        │
│   └── Contiguous sequence of compressed/stored blocks  │
├────────────────────────────────────────────────────────┤  Offset: footer.dict_offset
│ Optional Zstandard Dictionary (Raw bytes, dict_size)   │
├────────────────────────────────────────────────────────┤  Offset: FileSize - 76
│ Footer (Fixed 76 bytes, Little-Endian)                 │
└────────────────────────────────────────────────────────┘  Offset: FileSize
```

### 1.2 Footer Specification (76 Bytes Fixed)
Located at the exact end of the file (size constant and magics at `crates/onelf-format/src/footer.rs:53-55`, struct at `footer.rs:154-176`, field encoding in `write_to` at `footer.rs:213-225`; an earlier edition cited `footer.rs:14-28`, which is the doc-comment table) `[verified]`:

| Offset | Size (Bytes) | Field Name | Type / Encoding | Description |
|---|---|---|---|---|
| `0` | `8` | `magic` | `[u8; 8]` | Fixed magic byte sequence: `*b"ONELF\0\x01\x00"` |
| `8` | `2` | `format_version` | `u16` (LE) | Format version: `1` (legacy) or `2` (current format with structural hash chain) |
| `10` | `2` | `flags` | `u16` (LE) | Bitflags for container capabilities and launch policies |
| `12` | `8` | `manifest_offset` | `u64` (LE) | Absolute byte offset in file where compressed manifest begins |
| `20` | `8` | `manifest_compressed` | `u64` (LE) | Compressed size of manifest in bytes |
| `28` | `8` | `manifest_original` | `u64` (LE) | Uncompressed size of manifest in bytes |
| `36` | `8` | `payload_offset` | `u64` (LE) | Absolute byte offset where payload begins |
| `44` | `8` | `payload_size` | `u64` (LE) | Total size of payload section in bytes |
| `52` | `8` | `dict_offset` | `u64` (LE) | Offset of raw zstd dictionary (or `0` if absent) |
| `60` | `4` | `dict_size` | `u32` (LE) | Size of zstd dictionary in bytes (or `0` if absent) |
| `64` | `4` | `manifest_checksum` | `[u8; 4]` | Little-endian XXH32 of uncompressed manifest bytes |
| `68` | `8` | `end_magic` | `[u8; 8]` | Fixed trailer magic: `*b"FLENONE\0"` |

#### Footer Flags (`crates/onelf-format/src/footer.rs:66-101` `[verified]`):
- `1 << 0` (`HAS_DICT`): Package payload blocks were compressed against the embedded dictionary.
- `1 << 1` (`MEMFD_HINT`): Indicates potential eligibility for in-memory execution.
- `1 << 2`: Reserved (formerly reserved for sharun compatibility, never shipped).
- `1 << 3` (`STORED`): Payload blocks are raw uncompressed bytes (`compressed_size == original_size`).
- `1 << 4` (`EXTERNAL_UPDATER`): Package records an update URL but embeds no self-updater.
- `1 << 5` (`NO_HOST_LIB_DIRS`): Excludes host library directories (`HostLibsPolicy::Never`).
- `1 << 6` (`HOST_LIBS_ALWAYS`): Launch resolver may substitute any bundled soname (`HostLibsPolicy::Always`).
- `1 << 7` (`CACHE_REQUESTED`): Persistent disk cache allowed as final fallback.

### 1.3 Manifest Schema & Data Structures
The manifest is decompressed with zstd into memory. The layout is (`crates/onelf-format/src/manifest.rs:75-147` `[verified]`):

#### Manifest Header (114 Bytes in Version 3)
- `version` (`u16`): Currently `3` (`crates/onelf-format/src/manifest.rs:59`).
- `entry_count` (`u32`): Count of directory, file, and symlink entries.
- `string_table_size` (`u32`): Total byte length of string table pool.
- `entrypoint_count` (`u16`): Number of entrypoint descriptors.
- `default_entrypoint` (`u16`): Index into `entrypoints` array.
- `lib_dir_count` (`u16`): Number of library directory offsets.
- `name_offset` (`u16`): Offset into string table for package name.
- `package_id` (`[u8; 32]`): BLAKE3 of serialized manifest (with `package_id` and `footer_hash` zeroed).
- `prefix_hash` (`[u8; 32]`): BLAKE3 of the static runtime ELF prefix bytes `[0, manifest_offset)`.
- `footer_hash` (`[u8; 32]`): BLAKE3 of the 76-byte footer with layout fields zeroed.

#### Entrypoint Record (14 Bytes Fixed) (`crates/onelf-format/src/entry.rs:116-159` `[verified]`):
- `name` (`u32`): String table offset for entrypoint name.
- `target_entry` (`u32`): Index into `entries` array pointing to executable file.
- `args` (`u32`): String table offset for default arguments (delimited by `\x1f`).
- `working_dir` (`u8`): `0 = Inherit`, `1 = PackageRoot`, `2 = EntrypointParent`.
- `flags` (`u8`): Bit 0 = `MEMFD_ELIGIBLE`.

#### File/Directory/Symlink Entry Record (`crates/onelf-format/src/entry.rs:161-240` `[verified]`):
Serialized as a 65-byte header followed by `num_blocks * BLOCK_SIZE`:
- `kind` (`u8`): `0 = Dir`, `1 = File`, `2 = Symlink`.
- `parent` (`u32`): Parent directory entry index (`0xFFFFFFFF` for root entries). Directories must strictly precede their children (`manifest.rs:297-299`).
- `name` (`u32`): String table offset for path component. Component must be safe (`is_safe_component`: no `/`, `\0`, `.`, or `..`).
- `mode` (`u32`): POSIX permissions and mode bits.
- `mtime_secs` (`u64`) & `mtime_nsec` (`u32`): Modification timestamp.
- `content_hash` (`[u8; 32]`): BLAKE3 hash of entire uncompressed file content (zero for non-files).
- `num_blocks` (`u32`): Number of payload block descriptors.
- `symlink_target` (`u32`): String table offset for symlink target path. Must pass lexical validation (`symlink_target_within_root`) preventing root escapes.
- `blocks` (`[Block; num_blocks]`): Array of 56-byte block records.

#### Block Record (56 Bytes Fixed in Format v2/v3) (`crates/onelf-format/src/entry.rs:58-114` `[verified]`):
- `payload_offset` (`u64`): Relative offset into payload section.
- `compressed_size` (`u64`): Size of compressed block in bytes.
- `original_size` (`u64`): Decompressed block size in bytes (defaults to 64 KiB, max 32 MiB).
- `content_hash` (`[u8; 32]`): BLAKE3 hash of this block uncompressed bytes (allows single-block lazy verification without whole-file buffering). In manifest v1, this was absent (24-byte block).

---

## 2. Launch Resolver and GPU / Host Library Integration

### 2.1 Bundled vs. Host Selection Philosophy
`onelf` avoids `LD_LIBRARY_PATH` pollution (`crates/onelf-rt/src/env.rs:7-13`, commit `1e5385e` `[verified]`). Host library directories are never placed on the general search path because unbundled dependencies would silently load random host libraries into the bundled libc environment.

Instead, `onelf-format::resolve` uses **symbol version set comparison** (`verdef.rs`) and **materializes an ephemeral symlink farm** containing only approved host libraries (selection in `resolve()` at `resolve.rs:217-258`; farm written by `materialize()` at `resolve.rs:645-679`) `[verified]`.

### 2.2 Host Driver Discovery & Closure Walking
1. **Host Indexing (`HostIndex::load`, `resolve.rs:387-423`) `[verified]`**:
   - Reads `/etc/ld.so.cache` (or `$ONELF_LD_CACHE`) using `drivers::cache_paths_in`. Filters entries by native ABI flags (`FLAG_ABI_MASK`): `0x0300` for x86_64, `0x0a00` for aarch64, `0x0000` for x86_32. Hwcaps directories (`glibc-hwcaps`) are discarded if a base version exists (`drivers.rs:164-184`).
   - Scans Vulkan ICD and EGL vendor JSON directories (`ICD_DIRS`):
     - `/run/opengl-driver/share/vulkan/icd.d`, `/etc/vulkan/icd.d`, `/usr/share/vulkan/icd.d`
     - `/run/opengl-driver/share/glvnd/egl_vendor.d`, `/etc/glvnd/egl_vendor.d`, `/usr/share/glvnd/egl_vendor.d`
   - Parses the JSON files with a zero-alloc parser (`json_library_path`, `resolve.rs:518-525`) to find driver library paths (e.g. `libGLX_nvidia.so.0`, Mesa drivers).
2. **Driver Closure Computation (`driver_closure`, `resolve.rs:442-470`) `[verified]`**:
   - Seeds a BFS work queue with libraries matching `DRIVER_FAMILIES` (`drivers.rs:58-84`):
     `libGL.so`, `libGLX.so`, `libEGL.so`, `libGLdispatch.so`, `libOpenGL.so`, `libGLESv2.so`, `libvulkan.so`, `libcuda.so`, `libnvidia`, `libnvoptix`, `libamdhip64`, `libze_loader`, `libva.so`, `libva-drm.so`, `libva-x11.so`, `libva-wayland.so`, `libva-glx.so`, `libOpenCL.so`, `libdrm`, `libgbm.so`, plus ICD libraries.
   - For every library in the queue, reads `DT_NEEDED` records via ELF parsing (`verdef::read_needed`, `verdef.rs:86-92`) and transitively expands the closure.

### 2.3 Exact Symbol Version Resolution Logic
Symbol versions are parsed directly from the `SHT_GNU_VERDEF` ELF section (`crates/onelf-format/src/verdef.rs:76-82` `[verified]`).

```rust
// crates/onelf-format/src/verdef.rs:40-48 [verified]
pub fn compare(bundle: &VersionSet, host: &VersionSet) -> Choice {
    if host.is_subset(bundle) {
        Choice::Bundle
    } else if bundle.is_subset(host) {
        Choice::Host
    } else {
        Choice::Incomparable
    }
}
```
**Selection Rule (`crates/onelf-format/src/resolve.rs:348-366`) `[verified]`**:
- If `host.is_subset(bundle)`: The bundle defines all host versions (or both are equal / empty). `Choice::Bundle` wins. The bundled file is used.
- If `bundle.is_subset(host)`: The host library defines every version present in the bundle plus newer ones. `Choice::Host` wins. The host library is placed into the link farm.
- If neither is a subset: `Choice::Incomparable`. Bundle wins as safe fallback; recorded in `decision.incomparable`.

### 2.4 Glibc Version Conflicts and Loader Coupling
`libc.so.6` and the dynamic linker `ld-linux*.so` are strictly coupled:
```rust
// crates/onelf-format/src/resolve.rs:310-335 [verified]
if let (true, Some(bundled_libc), Some(host_libc)) =
    (req.host_libc, bundled.get(LIBC), host.libs.get(LIBC))
{
    let choice = verdef::compare(&versions(bundled_libc), &versions(host_libc));
    decision.compared.push((LIBC.to_string(), Some(choice)));
    match choice {
        Choice::Host => {
            if let Some(interp) = host.loader_for(host_libc) {
                for name in bundled.keys().filter(|n| is_libc_family(n)) {
                    let path = if name.starts_with("ld-linux") {
                        Some(interp.clone())
                    } else {
                        host.libs.get(name).cloned()
                    };
                    if let Some(path) = path {
                        decision.winners.insert(name.clone(), path);
                    }
                }
                decision.host_interp = Some(interp);
            }
        }
        ...
    }
}
```
If the host glibc is newer than the bundled glibc and `req.host_libc` is enabled:
1. The **entire glibc family** (`libc.so`, `libm.so`, `libpthread.so`, `libdl.so`, `librt.so`, `libresolv.so`, `libutil.so`, `libnss_*`, `ld-linux*`, etc., `resolve.rs:177-193`; the actual `LIBC_FAMILY` list is a superset of this and also includes `libanl.so`, `libBrokenLocale.so`, `libmvec.so`, `libc_malloc_debug.so`, `libthread_db.so`) is switched to the host copies as a unit.
2. The entrypoint is executed with the **host dynamic linker** (`decision.host_interp`), passed via the `ONELF_INTERP` environment variable to the injected bootstrap (set in `onelf-rt/src/launch.rs:332`, consumed by `env_interp_override` in `onelf-payloads/src/bootstrap.rs:659-673`; an earlier edition cited a nonexistent `bootstrap.rs:509-514`).
3. If host glibc is older or incompatible, the bundle glibc and loader remain active.

---

## 3. Execution-Mode Fallback Chain

`onelf-rt` attempts execution rungs in a strict waterfall (order comment and dispatch at `crates/onelf-rt/src/main.rs:160-333` `[verified]`):

```text
[Mode 1: memfd]
       │ (fails or not static/ineligible)
       ▼
[Mode 2: FUSE via User Namespace]
       │ (fails or user namespaces restricted / needs-setuid)
       ▼
[Mode 3: FUSE via fusermount3]
       │ (fails or fusermount3 helper absent)
       ▼
[Mode 4: Ephemeral tmpfs in User Namespace]
       │ (fails or memory insufficient / needs-setuid)
       ▼
[Mode 5: Runtime Directory (rundir)]
       │ (fails or space exceeded)
       ▼
[Mode 6: Persistent Disk Cache] (Opt-in only via ONELF_CACHE=1 or --cache)
```

### Detailed Mode Breakdown:

#### Mode 1: `memfd` (`crates/onelf-rt/src/memfd.rs` & `main.rs:166-226` `[verified]`)
- **Trigger**: Single static ELF entrypoint (no `DT_NEEDED`), or `[package] memfd = true`, and verified content hash matching BLAKE3.
- **Mechanism**: Calls `memfd_create("onelf", 0)` (`memfd.rs:16-17`; the fd name is `onelf`, there is no `MFD_CLOEXEC`, and no `F_ADD_SEALS`/`fchmod` sealing anywhere in the crate - an earlier edition's "seals it" was wrong). Decompresses the entrypoint payload into the memory fd (BLAKE3-verified against the entry's `content_hash` first, `main.rs:175-183`), then executes `/proc/self/fd/<fd>`. If memfd execution fails while not forced, the failure is silent and the ladder continues.
- **Privilege/Security**: Zero filesystem footprint. No mount or extraction.
- **Teardown**: Automatically reaped by kernel on process termination.

#### Mode 2: FUSE via User Namespace (`crates/onelf-rt/src/fuse/mount.rs:120-146` `[verified]`)
- **Trigger**: Default for standard packages with dynamic libraries.
- **Mechanism**: Calls `unshare(CLONE_NEWUSER | CLONE_NEWNS)`. Writes `deny` to `/proc/self/setgroups`, sets 1:1 mappings in `uid_map` and `gid_map`. Opens `/dev/fuse`, performs `mount("fuse", mountpoint, "fuse", MS_NOSUID | MS_NODEV | MS_NOATIME | MS_RDONLY, "fd=...,rootmode=40000,default_permissions")`. Forks child to exec target while parent serves in-tree FUSE loop.
- **Privilege/Security**: Requires unprivileged user namespaces (`kernel.unprivileged_userns_clone == 1` and unrestricted AppArmor). Skipped if package has `.onelf/needs-setuid` or `ONELF_FUSE_NO_NAMESPACE=1`.
- **Teardown**: Completely automatic by the Linux kernel when the last process in the mount namespace exits.

#### Mode 3: FUSE via `fusermount3` (`crates/onelf-rt/src/fuse/mount.rs:209-288` `[verified]`)
- **Trigger**: User namespaces disabled (e.g. Ubuntu 23.10+ AppArmor restrictions) or package requires setuid (`needs-setuid = true`).
- **Mechanism**: Creates `socketpair(AF_UNIX, SOCK_STREAM)`. Invokes `fusermount3 -o ro,nosuid,nodev,noatime,default_permissions -- <mountpoint>` with `_FUSE_COMMFD=<sock>`. Receives `/dev/fuse` fd via `SCM_RIGHTS` ancillary message.
- **Privilege/Security**: Requires SUID `fusermount3` (or SUID `fusermount`). Mount is host-visible.
- **Teardown & Cleanup**: Death pipe (`pipe2(O_CLOEXEC)`) detects child exit (`fuse/mod.rs:427-435`). On normal exit, parent unmounts via `fusermount3 -u -z -q`. If server was SIGKILLed, next launch sweeps stale disconnected mounts via `sweep_stale_mountpoints` (`paths.rs:298`).

#### FUSE Instance Sharing (`crates/onelf-rt/src/fuse/share.rs` `[verified]`):
Concurrent launches of the same package share a single FUSE mount and daemon:
- Server records state in `.onelf-onelf-<name>-<id8>.share` and clients acquire `.onelf-onelf-<name>-<id8>.lease`, where `<id8>` is the first 8 bytes of the package id as hex (`paths.rs:148-161`; an earlier edition showed the full package id).
- Subsequent launches enter the existing mount namespace (`setns(CLONE_NEWNS)`) or run from the host mountpoint, avoiding redundant decompression and memory page duplication.

#### Mode 4: Ephemeral tmpfs (`crates/onelf-rt/src/ephemeral.rs:57-130` `[verified]`)
- **Trigger**: FUSE `/dev/fuse` unavailable, but user namespaces permitted.
- **Mechanism**: `enter_namespace()`. Checks `/proc/meminfo` (`MemAvailable`) to verify package fits in RAM (`ephemeral.rs:40-53`). Mounts private `tmpfs` with `mount_tmpfs(size = content_size * 1.25)`. Decompresses package directly into tmpfs via `cache::extract_direct`. Execs entrypoint directly (no background FUSE daemon).
- **Teardown**: Kernel cleans up tmpfs when namespace closes.

#### Mode 5: Runtime Directory (`crates/onelf-rt/src/rundir.rs:26-160` `[verified]`)
- **Trigger**: No user namespaces, no FUSE helper available.
- **Mechanism**: Extracts into `$XDG_RUNTIME_DIR/onelf-<name>-<id8>-<pid>` or `/tmp/onelf-<uid>/<name>-<id8>-<pid>` (mode `0700`, `paths.rs:24-46,170-177`).
- **Teardown**: Forked parent monitors process death pipe. When all children and background daemons exit (`tree_quiet`, `rundir.rs:169-180`), the directory is recursively deleted.

#### Mode 6: Persistent Disk Cache (`crates/onelf-rt/src/cache.rs:155-256` `[verified]`)
- **Trigger**: Only when explicitly requested (`CACHE_REQUESTED` flag, `ONELF_CACHE=1`, or `ONELF_MODE=cache`).
- **Mechanism**: Extracts under `~/.cache/onelf/pkg/<package_id>/`. Stores deduplicated files in content-addressable store (`cas/<hash>`) with hardlinks into package directory.
- **Concurrency & GC**: Uses flock: `flock(LockShared)` on `lock/<package_id>` kept open through exec. Auto-GC (`auto_gc`) runs based on `ONELF_GC_MAX_AGE` (default 30 days) and acquires `flock(LockExclusive)`.

---

## 4. Self-Update Implementation

Implemented in `crates/onelf-rt/src/update.rs` (`[verified]`).

### 4.1 Remote Protocol & Transport Security
- **Strict HTTPS**: Enforced in `update.rs:45-48`. Cleartext HTTP is rejected unconditionally.
- **Remote Source**: Targets a `.zsync` control file at `[update].url` (e.g. `https://host/app.onelf.zsync`).
- **Detached Signature Location**: Derived by `onelf_format::update::detached_sig_url`: appends `.sig` before query parameters (e.g. `https://host/app.onelf.zsync.sig`).

### 4.2 Seeded Delta Download
- Uses `zsync-rs` (`ZsyncAssembly::from_url_with_client`).
- Submits the current binary `/proc/self/exe` as a local seed (`assembly.submit_source_file(self_path)`, `update.rs:338-340`).
- Only missing blocks are downloaded over HTTPS.

### 4.3 Cryptographic Verification & Anti-Rollback
1. **Ed25519 Detached Signature**: Downloaded binary is verified in memory (`update.rs:81-114`) against the embedded raw 32-byte public key (or keyring of concatenated keys) from `.onelf/update-key`. Uses `Mmap` to avoid heap allocations.
2. **Authenticated Revision Gate (`revision_permits`, `update.rs:285-304`)**:
   - Reads `.onelf/update-revision` from the staged package.
   - Refuses update if `downloaded_revision <= current_revision`.
   - If current package has a revision and downloaded does not, update is rejected.

### 4.4 Atomic Replacement & Rollback Recovery
```text
1. Staged write to unpredictable temp file: self_path.with_file_name(".onelf-update.<pid>.<random_hex>.tmp")
2. Claim temp file exclusively (O_CREAT | O_EXCL)
3. Delta assembly -> zsync verify -> Ed25519 signature verify -> revision check
4. Backup existing binary to sibling: `<self_path>.onelf-prev` + fsync
5. fsync staged file
6. Atomic rename: rename(staged_tmp, self_path)
7. fsync parent directory
8. If rename fails and binary is missing, restore from `<self_path>.onelf-prev`
```

---

## 5. Recipe Determinism and Build Reproducibility

### 5.1 Recipe Definition & Execution (`crates/onelf/src/recipe.rs` `[verified]`)
Defined in `onelf.toml`. Executed via `onelf build`.
Contains sections: `[package]`, `[[entrypoint]]`, `[compression]`, `[update]`, `[sysroot]`, `[bundle]`, `[paths]`, `[env]`, `preload`.
Parsed with `serde(deny_unknown_fields, rename_all = "kebab-case")`.

### 5.2 Determinism Safeguards (`PR #22` & `docs/guide/reproducible.md` `[verified]`)
- **Directory Traversal**: Sorted lexicographically via `jwalk` sort order.
- **Environment Sorting**: `[env]` deserializes into `BTreeMap<String, String>` ensuring sorted byte output in `.onelf/env`.
- **Timestamp Normalization**:
  - `mtime_nsec` is zeroed.
  - `SOURCE_DATE_EPOCH` clamps timestamps.
  - `[package] mtime = N` or `--mtime N` forces uniform timestamps across all entries.
  - In `[sysroot]` builds, mtimes default to `0` unless overridden (`reproducible.md:57-60`).
- **Attribution**: the mtime/`SOURCE_DATE_EPOCH` normalization, zeroed `mtime_nsec`, env `BTreeMap`, and sorted walks come from PR #22; the runtime `prefix_hash` is part of format v2 itself, not that PR (an earlier edition's "cargo registry path remapping" claim was unverified and is dropped).
- **Non-determinism Sources**: Upstream package mirror updates (e.g. debian apt snapshot shifts) if not pinned to snapshot.debian.org; dynamically traced host runs (`onelf bundle --trace`) if trace captures non-hermetic host configuration.

---

## 6. Startup Path, Compression, and Layout

### 6.1 Compression & Filesystem Engine
- Custom zstd block-compressed archive format (not SquashFS, not EROFS, not DwarFS).
- Block size defaults to 64 KiB (`6b08951 perf: default to 64 KiB payload blocks` `[verified]`).
- Optional zstd dictionary trained on files (`zstd::dict::from_continuous`).
- Uncompressed stored mode supported via `flags & STORED`.

### 6.2 Startup Flow and Latency Profile
1. **ELF Header Parsing & Footer Discovery**: `lseek` to `FileSize - 76`. Read footer. Validate magic bytes `ONELF\0\x01\x00` and `FLENONE\0`. (Sub-millisecond).
2. **Manifest Decompression**: Read `manifest_compressed` bytes at `manifest_offset`. Decompress with zstd. Verify the XXH32 manifest checksum (`loader.rs:61-67`). The `package_id` BLAKE3 is *not* recomputed at startup (it only names the cache directory); signature and `prefix_hash`/`footer_hash` checks happen only in `onelf verify` or self-update.
3. **Execution Mode Resolution**: Check `memfd` -> Check userns -> Check FUSE -> Check tmpfs.
4. **FUSE Mount**: If Mode 2, `unshare(CLONE_NEWUSER | CLONE_NEWNS)`, mount FUSE, fork worker daemon.
5. **Prefetch Optimization**: If the package contains a startup profile (stored as `.onelf/prefetch`, recorded at pack time from `ONELF_PROFILE` via `pack.rs:119-122`; an earlier edition called it `.onelf/startup.profile`, which exists nowhere), its blocks are decompressed ahead of demand by the FUSE server (`fuse/fs.rs:405+`; commit `822a654 feat: prefetch the blocks a startup profile lists` `[verified]`).
6. **Exec**: Entrypoint executed via dynamic linker or direct `execve`.

---

## 7. Open and Closed Issues, Pull Requests

- **Issue #36 (OPEN)**: "more arch support" (`riscv64`, `ppc64`, `ppc64le`, `loongarch64`) `[reported]`.
- **Issue #16 (CLOSED)**: "i686 build" (Addressed in PR #29, PR #30, and commit `7438f5a`) `[reported]`.
- **Issue #14 (CLOSED)**: "[FR] Desktop Integration" (Author implemented `onelf integrate` subcommand and docs `https://onelf.qaidvoid.dev/guide/desktop`) `[reported]`.
- **PR #31 (MERGED)**: "fix(rt): keep the bundled libraries out of the app children". Stops setting `LD_LIBRARY_PATH` globally, switching to `--library-path` on linker invocation `[verified]`.
- **PR #28 (MERGED)**: "feat: port bootstrap and env payloads to no_std Rust" for payload reproducibility `[verified]`.
- **PR #26 (MERGED)**: "refactor: doc hygiene, internal dedup, remove onelf-preload". Completely deleted the LD_PRELOAD interposer crate `onelf-preload` in favor of cleaner ELF patching `[verified]`.
- **PR #21 (MERGED)**: "fix: verify payload hashes and validate extraction paths" for critical integrity against path traversal `[verified]`.

---

## 8. Author Admissions: TODOs, FIXMEs, and Known Limitations

1. **Loader String Patching (`crates/onelf/src/bundle/elf.rs:1073-1090` `[verified]`)**:
   Patches `/etc/`, `/usr/`, `/nix/`, `/lib/` inside the bundled glibc dynamic linker to `/XXX/`, and `/lib64/` to the length-preserving `/XXX///` (`loader_scrub_list`, `bundle/elf.rs:1073-1090`), to prevent loading host `/etc/ld.so.preload` or host cache files.
2. **Dynamic Linker & Host Libc Coupling**:
   If host glibc has incompatible or newer symbol versions than bundled glibc, the entire glibc family must be swapped or remain bundled. If an application requires a host library that needs a newer glibc than bundled, but host glibc cannot be safely loaded, `Choice::Incomparable` forces bundled fallback, which can fail at runtime.
3. **No SUID Binary Support in userns**:
   FUSE in user namespaces explicitly rejects SUID binaries (`MS_NOSUID`). Packages needing SUID must fall back to `fusermount3` or fail.
4. **Kernel Version Floor**:
   Requires Linux 3.17+ for `memfd_create`, 3.8+ for unprivileged user namespaces. Cannot run on ancient 2.6.x kernels (unlike `Anylinux-AppImages` with `kernel_compat.rs`).

---

## 9. Git History Analysis (342 Commits)

- **v0.1.0 - v0.2.0 (Foundational Phase)**: Custom zstd block format with footer, `memfd` and FUSE execution modes from the earliest releases. No SquashFS appears anywhere in the repository's history (an earlier edition of this section claimed squashfs experiments; `git grep` over every tree and every commit message finds zero occurrences). `onelf-preload` (C/Rust `dlopen` interposer) enters in the 0.2.0 era (added in `6977832`, 2026-04-16).
- **v0.2.0 - v0.3.0 (Architecture Stabilization)**: Abandoned `onelf-preload` because `LD_PRELOAD` failed with statically linked binaries, broke with SUID, and leaked into subprocesses. Replaced with in-tree no_std Rust bootstrap payloads and binary ELF patching.
- **v0.3.0 - v0.4.0 (Hardening & Enterprise Polish)**: Format v2/v3 transition; Per-block 64 KiB BLAKE3 content hashing for lazy single-block FUSE verification; Strict HTTPS Ed25519 signed zsync updates with revision anti-rollback; Multi-process FUSE mount sharing (`crates/onelf-rt/src/fuse/share.rs`); Profile-guided startup block prefetching.
- **v0.4.1 (Current)**: i686 support; tuning default payload block size to 64 KiB; hardening FUSE server against race conditions.

---

## 10. Reality Check: Marketing Claims vs. Code Reality

| Claim in Docs / Site | Code Reality | Verdict |
|---|---|---|
| "Zero host dependencies" | True for static musl runtime prefix; dynamic apps still depend on kernel user namespaces or SUID `fusermount3` or `/dev/shm` tmpfs. | **Verified with Nuance** |
| "No LD_LIBRARY_PATH pollution" | Verified in PR #31 (`1e5385e`). Linker is invoked with `--library-path`; host-only paths set only when bootstrap requires it. | **Verified** |
| "In-memory execution without disk extraction" | Only available for static single binaries or packages marked `memfd = true`. Standard multi-file packages use FUSE or tmpfs. | **Verified** |
| "Automatic host GPU acceleration" | Implemented via symbol version comparison (`verdef.rs`) and ephemeral link farm. Does not bundle full Mesa (unlike Anylinux). Relies on host driver presence. | **Verified** |
| "Self-updating single binary" | Uses `zsync-rs` with Ed25519 signature checks. Verified in `update.rs`. Requires remote `.zsync` and `.sig` files. | **Verified** |
