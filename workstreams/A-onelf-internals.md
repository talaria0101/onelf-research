# Deep-Dive Technical Research Report: onelf Internal Architecture

**Target Repository:** `QaidVoid/onelf` (https://github.com/QaidVoid/onelf)  
**Analyzed Commits:** 351 commits; audited at HEAD `cd99efb` (2026-10-26), four commits past tag `0.4.2` (`e1a56af`, 2026-10-21; the repo tags releases without a `v` prefix). The previous edition audited `7438f5a`, one commit past tag `0.4.1`. Claims below say when they hold only at HEAD, which is not in any release.  
**Crates Analyzed:** `onelf`, `onelf-format`, `onelf-rt`, `onelf-sysroot`, `onelf-payloads` (and former `onelf-preload`)  
**Evidence Standard:** Every factual claim is marked as `[verified]` (observed directly in code/docs), `[reported]` (stated in GitHub PR/issue/commit messages), or `[inferred]` (derived through technical deduction).

---

## 1. Binary Format and Manifest Schema

### 1.1 Physical File Layout & Alignment
An `onelf` executable is a contiguous, self-contained ELF executable container consisting of up to five concatenated sections (`docs/reference/file-format.md:3-25` `[verified]`):

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
│   ├── blocks payload: compressed/stored blocks         │
│   └── or, with STIPPLE_PAYLOAD, one stipplefs image    │
├────────────────────────────────────────────────────────┤  Offset: footer.dict_offset
│ Optional Zstandard Dictionary (Raw bytes, dict_size)   │
├────────────────────────────────────────────────────────┤  Offset: FileSize - 76
│ Footer (Fixed 76 bytes, Little-Endian)                 │
└────────────────────────────────────────────────────────┘  Offset: FileSize
```

### 1.2 Footer Specification (76 Bytes Fixed)
Located at the exact end of the file (size constant and magics at `crates/onelf-format/src/footer.rs:53-55`, struct at `footer.rs:162-184`, field encoding in `write_to` at `footer.rs:222-236`; an earlier edition cited `footer.rs:14-28`, which is the doc-comment table) `[verified]`:

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
| `64` | `4` | `manifest_checksum` | `[u8; 4]` | Little-endian XXH32 of uncompressed manifest bytes (for version 3+, computed with the `footer_hash` header field zeroed) |
| `68` | `8` | `end_magic` | `[u8; 8]` | Fixed trailer magic: `*b"FLENONE\0"` |

#### Footer Flags (`crates/onelf-format/src/footer.rs:66-109` `[verified]`):
- `1 << 0` (`HAS_DICT`): Package payload blocks were compressed against the embedded dictionary.
- `1 << 1` (`MEMFD_HINT`): Indicates potential eligibility for in-memory execution.
- `1 << 2`: Reserved (formerly reserved for sharun compatibility, never shipped).
- `1 << 3` (`STORED`): Payload blocks are raw uncompressed bytes (`compressed_size == original_size`).
- `1 << 4` (`EXTERNAL_UPDATER`): Package records an update URL but embeds no self-updater.
- `1 << 5` (`NO_HOST_LIB_DIRS`): Excludes host library directories (`HostLibsPolicy::Never`).
- `1 << 6` (`HOST_LIBS_ALWAYS`): Launch resolver may substitute any bundled soname (`HostLibsPolicy::Always`).
- `1 << 7` (`CACHE_REQUESTED`): Persistent disk cache allowed as final fallback.
- `1 << 8` (`CACHE_PREFERRED`, 0.4.2): The cache is tried before every other mode (`--prefer-cache`). Set together with bit 7 so a runtime that predates it still falls back to the cache.
- `1 << 9` (`STIPPLE_PAYLOAD`, 0.4.2): The payload region is a stipplefs image (see 1.4). A reader that predates the flag fails every hash check rather than serving wrong bytes (`docs/reference/file-format.md`).

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

#### Entrypoint Record (14 Bytes Fixed) (`crates/onelf-format/src/entry.rs:122-165` `[verified]`):
- `name` (`u32`): String table offset for entrypoint name.
- `target_entry` (`u32`): Index into `entries` array pointing to executable file.
- `args` (`u32`): String table offset for default arguments (delimited by `\x1f`).
- `working_dir` (`u8`): `0 = Inherit`, `1 = PackageRoot`, `2 = EntrypointParent`.
- `flags` (`u8`): Bit 0 = `MEMFD_ELIGIBLE`.

#### File/Directory/Symlink Entry Record (`crates/onelf-format/src/entry.rs:167-252` `[verified]`):
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

#### Block Record (56 Bytes Fixed in Format v2/v3) (`crates/onelf-format/src/entry.rs:64-120` `[verified]`):
- `payload_offset` (`u64`): Relative offset into payload section.
- `compressed_size` (`u64`): Size of compressed block in bytes.
- `original_size` (`u64`): Decompressed block size in bytes (default 64 KiB; the packer accepts 4 KiB to 32 MiB, `docs/reference/file-format.md:139`; the reader rejects anything above 256 MiB, `reader.rs:103-106`).
- `content_hash` (`[u8; 32]`): BLAKE3 hash of this block uncompressed bytes (allows single-block lazy verification without whole-file buffering). In manifest v1, this was absent (24-byte block).

### 1.4 The stipplefs Payload (0.4.2) `[verified in source; sizes measured in ../measurements/README.md]`
With `--payload stipple` (or `[compression] payload = "stipple"`) the packer sets `STIPPLE_PAYLOAD` and the payload region is one [stipplefs](https://github.com/QaidVoid/stipplefs) image (`crates/onelf/src/pack.rs:1838`, `crates/onelf-format/src/payload.rs`). The manifest still lists every file with its blocks and BLAKE3 hashes, but a block now describes a 64 KiB slice (`SLICE_SIZE`, `payload.rs`) of its file: `payload_offset` is the slice's offset within the file, `compressed_size` holds the file's inode in the image, `original_size` is the slice length, and `content_hash` is the BLAKE3 of the slice (`entry.rs:58-64`, `file-format.md`). The reader opens the image once per process at `payload_offset` for `payload_size` bytes (`Codec::open`, `payload.rs:41-60`) and serves slices with positional reads through the file handle (`read_slice`, `payload.rs:72-85`); every slice is hash-checked like a decompressed block (`loader.rs:94-108`).

Packer settings, from `stipple_payload`: image block size 32 MiB by default, any power of two up to 64 MiB (`--block-size`); content-defined chunks of 4096 bytes on average; codecs zstd, zstd with dictionary, and each of those behind an x86 branch filter (BCJ), or stored only with `--no-compress`; a 112 KiB trained dictionary unless the block size exceeds 1 MiB or the payload is stored; files ordered by extension, with the `prefetch` profile as the image's hot list; the image's own times are clamped because the manifest carries each entry's. `--dict` is refused. After building the image the packer reads every file back out of it, in image order, to record the slices, so the manifest describes the image rather than the source (`pack.rs` comment above `stipple_payload`). Extraction and cache population read files in image order (`file_order`, `payload.rs:93-110`) because reading by path would decode a 32 MiB block again for every file in it.

Two properties that bear on other sections: (1) the footer flag is outside `package_id` (observed: a `--prefer-cache` package and a plain one built from the same tree and options had the same package id, so the cache directory name did not change); (2) a compressed image's bytes are not stable across builds, which is why delta updates need `--no-compress` for stipple payloads (section 4.2).

---

## 2. Launch Resolver and GPU / Host Library Integration

### 2.1 Bundled vs. Host Selection Philosophy
`onelf` avoids `LD_LIBRARY_PATH` pollution (`crates/onelf-rt/src/env.rs:7-13`, commit `1e5385e` `[verified]`). Host library directories are never placed on the general search path because unbundled dependencies would silently load random host libraries into the bundled libc environment.

Instead, `onelf-format::resolve` uses **symbol version set comparison** (`verdef.rs`) and **materializes an ephemeral symlink farm** containing only approved host libraries (selection in `resolve()` at `resolve.rs:224-267`; farm written by `materialize()` at `resolve.rs:689-722`) `[verified]`.

### 2.2 Host Driver Discovery & Closure Walking
1. **Host Indexing (`HostIndex::load`, `resolve.rs:401-450`) `[verified]`**:
   - Reads `/etc/ld.so.cache` (or `$ONELF_LD_CACHE`) using `drivers::cache_paths_in`. Filters entries by native ABI flags (`FLAG_ABI_MASK`): `0x0300` for x86_64, `0x0a00` for aarch64, `0x0000` for x86_32. Hwcaps directories (`glibc-hwcaps`) are discarded if a base version exists (`drivers.rs:164-184`).
   - Scans Vulkan ICD and EGL vendor JSON directories (`ICD_DIRS`):
     - `/run/opengl-driver/share/vulkan/icd.d`, `/etc/vulkan/icd.d`, `/usr/share/vulkan/icd.d`
     - `/run/opengl-driver/share/glvnd/egl_vendor.d`, `/etc/glvnd/egl_vendor.d`, `/usr/share/glvnd/egl_vendor.d`
   - Parses the JSON files with a zero-alloc parser (`json_library_path`, `resolve.rs:559-566`) to find driver library paths (e.g. `libGLX_nvidia.so.0`, Mesa drivers).
2. **Driver Closure Computation (`driver_closure`, `resolve.rs:470-498`) `[verified]`**:
   - Seeds a BFS work queue with libraries matching `DRIVER_FAMILIES` (`drivers.rs:58-84`):
     `libGL.so`, `libGLX.so`, `libEGL.so`, `libGLdispatch.so`, `libOpenGL.so`, `libGLESv2.so`, `libvulkan.so`, `libcuda.so`, `libnvidia`, `libnvoptix`, `libamdhip64`, `libze_loader`, `libva.so`, `libva-drm.so`, `libva-x11.so`, `libva-wayland.so`, `libva-glx.so`, `libOpenCL.so`, `libdrm`, `libgbm.so`, plus ICD libraries.
   - For every library in the queue, reads `DT_NEEDED` records via ELF parsing (`verdef::read_needed`, `verdef.rs:86-92`) and transitively expands the closure.
   - Two seeds were added after 0.4.2, at HEAD only (commits `1db8d66`, `1f12826`, 2026-10-22): any host library whose name starts with `libGLX_` (`HOST_SEEDS`, `resolve.rs:100`), because glvnd opens `libGLX_<vendor>` by a name the X server supplies and nothing else names it; and everything the host's DRI driver modules need. `module_dirs` takes the `dri` directory beside each library directory in the loader cache (`resolve.rs:501-510`), `HostIndex::load` reads `DT_NEEDED` of every `*.so` in them into `module_needs`, and `driver_closure` queues those names (`resolve.rs:401-450`, `470-498`). Mesa and libva open those modules by absolute path, so before the change their own dependencies never reached the farm (commit message of `1f12826`). Both are covered by unit tests in `resolve.rs` that use fixture ELF bytes; neither was run against a real Mesa here.

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
**Selection Rule (`crates/onelf-format/src/resolve.rs:355-373`) `[verified]`**:
- If `host.is_subset(bundle)`: The bundle defines all host versions (or both are equal / empty). `Choice::Bundle` wins. The bundled file is used.
- If `bundle.is_subset(host)`: The host library defines every version present in the bundle plus newer ones. `Choice::Host` wins. The host library is placed into the link farm.
- If neither is a subset: `Choice::Incomparable`. Bundle wins as safe fallback; recorded in `decision.incomparable`.

### 2.4 Glibc Version Conflicts and Loader Coupling
`libc.so.6` and the dynamic linker `ld-linux*.so` are strictly coupled:
```rust
// crates/onelf-format/src/resolve.rs:312-335 [verified]
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
1. The **entire glibc family** (`libc.so`, `libm.so`, `libpthread.so`, `libdl.so`, `librt.so`, `libresolv.so`, `libutil.so`, `libnss_*`, `ld-linux*`, etc., `resolve.rs:184-200`; the actual `LIBC_FAMILY` list is a superset of this and also includes `libanl.so`, `libBrokenLocale.so`, `libmvec.so`, `libc_malloc_debug.so`, `libthread_db.so`) is switched to the host copies as a unit.
2. The entrypoint is executed with the **host dynamic linker** (`decision.host_interp`), passed via the `ONELF_INTERP` environment variable to the injected bootstrap (set in `onelf-rt/src/launch.rs:346`, consumed by `env_interp_override` in `onelf-payloads/src/bootstrap.rs:659-673`; an earlier edition cited a nonexistent `bootstrap.rs:509-514`).
3. If host glibc is older or incompatible, the bundle glibc and loader remain active.

---

## 3. Execution-Mode Fallback Chain

`onelf-rt` attempts execution rungs in a strict waterfall (order comment and dispatch at `crates/onelf-rt/src/main.rs:169-370` `[verified]`):

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

With `CACHE_PREFERRED` (0.4.2, `--prefer-cache`) the order changes: memfd is skipped (`main.rs:181`), the cache is tried first (`main.rs:260-273`), and if its extraction fails the runtime prints `trying the other execution modes` and continues down the ladder. A forced `ONELF_MODE` ignores the preference (`force.is_none() &&`). Observed on the 0.4.2 release, 2026-10-28: a `--prefer-cache` package ran from `~/.cache/onelf/pkg/<package_id>/` with `XDG_CACHE_HOME` set. The `exec_cache` function (`main.rs:372`) now holds the cache rung so both call sites share it.

### Detailed Mode Breakdown:

#### Mode 1: `memfd` (`crates/onelf-rt/src/memfd.rs` & `main.rs:180-237` `[verified]`)
- **Trigger**: The default entrypoint is a static ELF (no `DT_NEEDED`) or the package sets `[package] memfd = true`, and its content hash verifies with BLAKE3; other entrypoints start at the next rung (`docs/guide/execution-modes.md`). No package tree exists in this mode (`ONELF_DIR` empty, `[paths]` not applied). The project's own docs say a fully static binary can simply be shipped directly (`docs/guide/introduction.md`), so this rung serves a case where packaging adds little.
- **Mechanism**: Calls `memfd_create("onelf", 0)` (`memfd.rs:16-17`; the fd name is `onelf`, there is no `MFD_CLOEXEC`, and no `F_ADD_SEALS`/`fchmod` sealing anywhere in the crate - an earlier edition's "seals it" was wrong). Decompresses the entrypoint payload into the memory fd (BLAKE3-verified against the entry's `content_hash` first, `main.rs:198-203`), then executes `/proc/self/fd/<fd>`. If memfd execution fails while not forced, the failure is silent and the ladder continues.
- **Privilege/Security**: Zero filesystem footprint. No mount or extraction.
- **Teardown**: Automatically reaped by kernel on process termination.

#### Mode 2: FUSE via User Namespace (`crates/onelf-rt/src/fuse/mount.rs:32-146` `[verified]`; `enter_namespace`/`unshare_and_map` at 32-65 do the unshare and id maps, `fuse_mount_unshare` at 120-146 the mount)
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
- Server records state in `.onelf-<name>-<id8>.share` and clients acquire `.onelf-<name>-<id8>.lease`, where `<id8>` is the first 8 bytes of the package id as hex (`paths.rs:148-161`; an earlier edition showed the full package id, and an even earlier one doubled the `onelf-` prefix).
- Subsequent launches enter the existing mount namespace (`setns(CLONE_NEWNS)`) or run from the host mountpoint, avoiding redundant decompression and memory page duplication.
- Doc/code disagreement: `docs/guide/execution-modes.md` says the record is named by the package's "whole id", but `shared_dir_name` uses the first 8 bytes (`paths.rs:148-153`). The code is what this report documents; the docs page looks stale.

#### Dependency sets (cross-package sharing; added in 0.4.0, commits `e72b17a`..`21797eb`, 2026-09-06) `[verified: docs/guide/sysroot.md; code not run]`
A recipe can name a shared set (`[sysroot.sets.<name>]` with URL and BLAKE3, built by `onelf sysroot pack-set`): the closure of named sysroot packages, left out of the bundle. At launch the set is fetched into the shared cache, verified, and by default served by one detached FUSE server whose mountpoint is named by the set's hash, so every package naming the same set shares one download, one mount, one server and one block cache. The mount is in the host mount namespace and needs `fusermount3`; without it the set is copied out (`ONELF_SET_MODE=extract` forces that). Sets are obtained before an execution mode is chosen for that reason. Set libraries appear as symlinks in the bundle's library directory; nothing goes on `LD_LIBRARY_PATH`. The first edition of this report did not mention sets and so claimed there was no cross-package sharing.

#### Mode 4: Ephemeral tmpfs (`crates/onelf-rt/src/ephemeral.rs:57-130` `[verified]`)
- **Trigger**: FUSE `/dev/fuse` unavailable, but user namespaces permitted.
- **Mechanism**: `enter_namespace()`. Checks `/proc/meminfo` (`MemAvailable`) to verify package fits in RAM (`ephemeral.rs:40-53`). Mounts private `tmpfs` with `mount_tmpfs(size = content_size * 1.25)`. Decompresses package directly into tmpfs via `cache::extract_direct`. Execs entrypoint directly (no background FUSE daemon).
- **Teardown**: Kernel cleans up tmpfs when namespace closes.

#### Mode 5: Runtime Directory (`crates/onelf-rt/src/rundir.rs:26-160` `[verified]`)
- **Trigger**: No user namespaces, no FUSE helper available.
- **Mechanism**: Extracts into `$XDG_RUNTIME_DIR/onelf-<name>-<id8>-<pid>` or `/tmp/onelf-<uid>/onelf-<name>-<id8>-<pid>` (mode `0700`, `paths.rs:24-52,170-177`). Here `<id8>` is the first 4 bytes of the package id as hex - 8 hex characters - via `package_dir_name`/`launch_dir_name` (`paths.rs:169-178`), a shorter prefix than the shared mount's 8-byte one.
- **Teardown**: Forked parent monitors process death pipe. When all children and background daemons exit (`tree_quiet`, `rundir.rs:169-180`), the directory is recursively deleted.

#### Mode 6: Persistent Disk Cache (`crates/onelf-rt/src/cache.rs:152-253` `[verified]`)
- **Trigger**: Only when explicitly requested (`CACHE_REQUESTED` flag, `ONELF_CACHE=1`, or `ONELF_MODE=cache`), or first of all with `CACHE_PREFERRED`.
- **Mechanism**: Extracts under `~/.cache/onelf/pkg/<package_id>/`. Stores deduplicated files in content-addressable store (`cas/<2-hex-char shard>/<blake3hex>-<mode>`, `cache.rs:276-283`) with hardlinks into package directory.
- **Order**: files are extracted in the image's own order for a stipple payload (`payload::file_order`, `cache.rs:90,269`), not manifest order.
- **Concurrency & GC**: Uses flock: `flock(LockShared)` on `lock/<package_id>` kept open through exec (`cache.rs:181-184`, inheritable fd per `paths.rs:54-60`). Auto-GC (`auto_gc`, `cache.rs:419-460`) runs based on `ONELF_GC_MAX_AGE` in days (default 30, `main.rs:399-406`) and acquires a non-blocking `flock(NonBlockingLockExclusive)` per victim (`cache.rs:481`), removing at most 5 packages per run.

#### argv[0] of the app (0.4.2, commit `be446cc`) `[verified: launch.rs:159-169; observed]`
The app now receives the tree path of its target as `argv[0]` (not the path of the pack), and `ONELF_ARGV0` keeps the name the user launched. An entrypoint whose name differs from its target's file name keeps the launched name, because a multicall binary dispatches on it. Observed on the 0.4.2 release: a script printing `$0` showed `/workspace/m/cache/onelf/pkg/<id>/bin/run`.

---

## 4. Self-Update Implementation

**Which version.** Release 0.4.2 (tag `e1a56af`) updates through `zsync-rs` against a `.zsync` control file (`crates/onelf-rt/Cargo.toml:11,20` and line 328 of `update.rs`, at that tag). HEAD `cd99efb` (PR #41, unreleased) replaces that with direct-release delta updates, described below. Both versions are `[verified]` in source. Neither update path was run in this pass: 0.4.2 was checked only as far as `--onelf-update` printing its disabled message for a package with a URL and no key, and HEAD has no runnable binary here.

### 4.1 Release 0.4.2: zsync
- HTTPS enforced, `.zsync` control file at `[update].url`, signature at the URL plus `.sig` (so `app.onelf.zsync.sig`), seeded delta through `ZsyncAssembly::from_url_with_client` and `submit_source_file(self_path)`, then Ed25519 verification and the revision gate. Packages with a URL and no key refuse to update.

### 4.2 HEAD: direct-release delta update (`crates/onelf-rt/src/update/`)
Module split: `mod.rs` (policy, signature, install), `range.rs` (HTTPS range transport, remote probe), `delta.rs` (plan and assemble); 4,068 lines including unit tests, against the 722 of the old `update.rs`.

1. **Transport** (`update/mod.rs:79-104`, `update/mod.rs:884-925`, `range.rs`): a URL not starting with `https://` is refused with exit 2 before any request; the agent is HTTPS-only, follows redirects, and carries `Range` and `If-Range` (strong ETag only) across them (`range.rs:210-216`). Size comes from `HEAD`, falling back to a `Range: bytes=0-0` request (`range.rs:126-200`). A host answering a range with a plain 200 is marked as not honoring ranges and every later range request fails with `NoRanges` without another round trip (`range.rs:66-69`), which makes the caller download the whole file.
2. **Probe** (`range.rs:343-430`): footer by explicit range, then the compressed manifest by explicit range, each validated like a local package (footer against size, manifest against XXH32); the manifest read is capped at 256 MiB (`MAX_PROBE_READ`, `range.rs:341`). No suffix or multi-range request is ever made, which matches what GitHub release assets accept (re-observed 2026-10-28: `bytes=-76` and `bytes=0-1,5-6` answered 501, explicit single ranges 206).
3. **Freshness** (`update/mod.rs:222-267`): equal `package_id` (covers every content hash and the runtime prefix) prints `up to date`. If the running package carries a revision, a differing id is not enough, so the check fetches and verifies the update as an apply would and reports `no update offered` when the revision gate refuses it.
4. **Plan** (`delta.rs`): blocks payloads reuse a block only when both packages use the same dictionary, and every copied block is decoded and re-hashed first (`delta.rs:11-15`). Stipple payloads are planned from the image's own metadata and only stored (`--no-compress`) images qualify; a compressed image falls back to a full download with a message on stderr (`delta.rs:16-23`). Spans under 128 KiB apart are merged into one request (`delta.rs:220`).
5. **Verification** (`update/mod.rs:106-155`, `update/mod.rs:467-510`, `update/mod.rs:551-652`): the detached signature is fetched first, so an unsigned release fails before any of the package is downloaded; it is verified against the assembled file through the staged file's handle, using an mmap, against any key of the keyring in `.onelf/update-key` (concatenated 32-byte Ed25519 keys). If any bytes were copied and verification fails, the update is downloaded in full and verified again. Unsigned policy (`policy`, `update/mod.rs:57-77`): a package carrying the `.onelf/update-unsigned` marker and no key is verified only against its manifest (`verify_unsigned`, `update/mod.rs:467`), with a stderr warning on every update; a package with both exits 2; a URL with neither leaves self-update disabled (exit 1).
6. **Revision gate** (`revision_permits`, `update/mod.rs:512`): the staged package's `.onelf/update-revision` must be strictly newer than the running one; a running package with a revision refuses a release without one; an unparsable revision on the running package is a broken package and exits 2 (`main.rs:128-137`).
7. **Install** (`apply`, `update/mod.rs:676`; `install_staged`, `update/mod.rs:729`): an exclusive lock on the running binary's inode (`InstallLock`, `update/mod.rs:210`), a staging file `<name>.onelf-update.<pid>.<random>.tmp` created exclusively (`update/mod.rs:343-375`), the rollback copy `<name>.onelf-prev` saved from the locked handle (`update/mod.rs:399`), the verified inode compared with the path immediately before the atomic `rename`, a restore from the rollback copy if the rename fails and the binary is missing, and an fsync of the parent directory.

Exit codes changed in places: the update path now returns 2 where it returned 1 for an invalid UTF-8 update URL and an unresolvable `/proc/self/exe` (`main.rs:102-127`).

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
  - In `[sysroot]` builds, mtimes default to `0` unless overridden (`reproducible.md:60-63`).
- **Attribution**: the mtime/`SOURCE_DATE_EPOCH` normalization, zeroed `mtime_nsec`, env `BTreeMap`, and sorted walks come from PR #22; the runtime `prefix_hash` is part of format v2 itself, not that PR (an earlier edition's "cargo registry path remapping" claim was unverified and is dropped).
- **Non-determinism Sources**: Upstream package mirror updates (e.g. debian apt snapshot shifts) if not pinned to snapshot.debian.org; dynamically traced host runs (`onelf bundle --trace`) if trace captures non-hermetic host configuration.

---

## 6. Startup Path, Compression, and Layout

### 6.1 Compression & Filesystem Engine
- Two payload formats (not SquashFS, not EROFS, not DwarFS): the default custom zstd block-compressed format, and since 0.4.2 a stipplefs image (section 1.4) that deduplicates content-defined chunks across files and compresses many files per 32 MiB block. Measured sizes of both against DwarFS are in `../measurements/README.md`.
- Block size defaults to 64 KiB (`6b08951 perf: default to 64 KiB payload blocks` `[verified]`; `compress.rs:15`). The recipe reference reports, for Blender, 64 KiB starting 17 percent faster from a cold cache than 256 KiB for a package 5 percent larger, and 1 MiB 40 percent slower than 256 KiB (`docs/reference/recipe-schema.md:102-106`) [author's figures, not reproduced]. `docs/guide/introduction.md` still draws 256 KB blocks; the code default is 64 KiB.
- Identical files are stored once per package (`pack.rs:1296`; `docs/reference/file-format.md`). The blocks payload has no cross-file block dedup; the stipple payload does (4 KiB average chunk).
- Optional zstd dictionary trained on files (`zstd::dict::from_continuous`).
- Uncompressed stored mode supported via `flags & STORED`.

### 6.2 Startup Flow and Latency Profile
1. **ELF Header Parsing & Footer Discovery**: `lseek` to `FileSize - 76`. Read footer. Validate magic bytes `ONELF\0\x01\x00` and `FLENONE\0`. [latency unmeasured]
2. **Manifest Decompression**: Read `manifest_compressed` bytes at `manifest_offset`. Decompress with zstd. Verify the XXH32 manifest checksum (`loader.rs:67-73`). No timing exists for any of this phase. The `package_id` BLAKE3 is *not* recomputed at startup (it only names on-disk paths: the cache tree, the lock file, and the private launch/mountpoint names); `prefix_hash`/`footer_hash` are checked only by `onelf verify` (`crates/onelf/src/verify.rs:54-75`), while the Ed25519 signature check runs in `onelf verify` and in self-update, which references neither structure hash.
3. **Execution Mode Resolution**: Check `memfd` -> Check userns -> Check FUSE -> Check tmpfs.
4. **FUSE Mount**: If Mode 2, `unshare(CLONE_NEWUSER | CLONE_NEWNS)`, mount FUSE, fork worker daemon.
5. **Prefetch Optimization**: If the package contains a startup profile (stored as `.onelf/prefetch`, recorded at pack time from `ONELF_PROFILE` via `pack.rs:158-161`; an earlier edition called it `.onelf/startup.profile`, which exists nowhere), its blocks are decompressed ahead of demand by the FUSE server (with a stipple payload the packer also passes the profile to the image as its hot list, so the startup reads sit together at the front of the image) (`fuse/fs.rs:406+`; commit `822a654 feat: prefetch the blocks a startup profile lists` `[verified]`).
6. **Exec**: Entrypoint executed via dynamic linker or direct `execve`.

---

## 7. Open and Closed Issues, Pull Requests

- **Issue #36 (OPEN)**: "more arch support" (`riscv64`, `ppc64`, `ppc64le`, `loongarch64`) `[verified: GitHub API 2026-10-18, re-checked with `gh issue list` 2026-10-28 - state open, title and arch list match the issue body]`.
- **Issue #16 (CLOSED)**: "i686 build" (Addressed in PR #29, PR #30, and commit `7438f5a`) `[verified: GitHub API - state closed; PRs #29/#30 are commits 4eed307/914cdc1 and 7438f5a is the i686 GOT fix, all in git history]`.
- **PR #41 (MERGED 2026-10-26)**: "feat: replace zsync with direct-release delta self-updates" `[verified: gh pr list, 2026-10-28]`. **PR #40 (OPEN)**: "chore: release v0.4.3" `[verified]`.
- **Issue #14 (CLOSED)**: "[FR] Desktop Integration" (Author implemented `onelf integrate` subcommand and docs `https://onelf.qaidvoid.dev/guide/desktop`) `[verified: GitHub API - state closed; Integrate/Unintegrate subcommands in crates/onelf/src/main.rs:309,320, crates/onelf/src/integrate.rs exists, docs page returns HTTP 200]`.
- **PR #31 (MERGED)**: "fix(rt): keep the bundled libraries out of the app children". Stops setting `LD_LIBRARY_PATH` globally, switching to `--library-path` on linker invocation `[verified]`.
- **PR #28 (MERGED)**: "feat: port bootstrap and env payloads to no_std Rust" for payload reproducibility `[verified]`.
- **PR #26 (MERGED)**: "refactor: doc hygiene, internal dedup, remove onelf-preload". Completely deleted the LD_PRELOAD interposer crate `onelf-preload` in favor of cleaner ELF patching `[verified]`.
- **PR #21 (MERGED)**: "fix: verify payload hashes and validate extraction paths" for critical integrity against path traversal `[verified]`.

---

## 8. Author Admissions: TODOs, FIXMEs, and Known Limitations

1. **Loader String Patching (`crates/onelf/src/bundle/elf.rs:1070-1087` `[verified]`)**:
   Patches `/etc/`, `/usr/`, `/nix/`, `/lib/` inside the bundled glibc dynamic linker to `/XXX/`, and `/lib64/` to the length-preserving `/XXX///` (`loader_scrub_list`, `bundle/elf.rs:1070-1087`), to prevent loading host `/etc/ld.so.preload` or host cache files.
2. **Dynamic Linker & Host Libc Coupling**:
   If host glibc has incompatible or newer symbol versions than bundled glibc, the entire glibc family must be swapped or remain bundled. If an application requires a host library that needs a newer glibc than bundled, but host glibc cannot be safely loaded, `Choice::Incomparable` forces bundled fallback, which can fail at runtime.
3. **No SUID Binary Support in userns**:
   FUSE in user namespaces explicitly rejects SUID binaries (`MS_NOSUID`). Packages needing SUID must fall back to `fusermount3` or fail.
4. **Kernel Version Floor** [inferred; the project documents none]:
   The memfd mode needs Linux 3.17+ and the namespace modes 3.8+ (FUSE in a user namespace 4.18+). The runtime-directory mode needs neither, so these are per-mode floors. Whether the runtime runs on 2.6.x kernels was not tested. Anylinux's emulation layer (`kernel_compat.rs`) does target them, on x86_64 only.

---

## 9. Git History Analysis (351 Commits)

- **v0.1.0 - v0.2.0 (Foundational Phase)**: Custom zstd block format with footer, `memfd` and FUSE execution modes from the earliest releases. No SquashFS appears anywhere in the repository's history (an earlier edition of this section claimed squashfs experiments; `git grep` over every tree and every commit message finds zero occurrences). `onelf-preload` (a Rust `cdylib` exposing a C ABI that intercepted `execve` under `LD_PRELOAD`) enters in the 0.2.0 era (added in `6977832`, 2026-04-16).
- **v0.2.0 - v0.3.0 (Architecture Stabilization)**: Abandoned `onelf-preload` because `LD_PRELOAD` failed with statically linked binaries, broke with SUID, and leaked into subprocesses `[inferred]` (no commit or doc states the full rationale; docs only partly support it - `docs/guide/recipe.md:267` on the interpreter being wiped by a sandboxed re-exec, `docs/reference/env-vars.md:11` on setuid ignoring `ONELF_*`). Replaced with in-tree no_std Rust bootstrap payloads and binary ELF patching.
- **v0.3.0 - v0.4.0 (Hardening & Enterprise Polish)** (0.4.0 also added shared dependency sets, a fetchable pinned GL build and `onelf-env` exec hooks that restore the caller's environment for host programs): Format v2/v3 transition; Per-block 64 KiB BLAKE3 content hashing for lazy single-block FUSE verification; Strict HTTPS Ed25519 signed zsync updates with revision anti-rollback; Multi-process FUSE mount sharing (`crates/onelf-rt/src/fuse/share.rs`); Profile-guided startup block prefetching.
- **v0.4.1**: i686 payload fixes (`0d655cf` lets bootstrap asserts link without a GOT, `7438f5a` allows the i686 GOT header and forbids relocations instead); a test hardening reclamation of a shared FUSE mount after a killed server (`b55fbd5`). (i686 support itself shipped earlier, in 0.3.0/0.3.1 via PRs #29/#30; the 64 KiB payload block-size default landed in 0.4.0 via `6b08951`; multi-process FUSE mount sharing shipped in 0.4.0 via `900a7a9`.)
- **v0.4.2 (latest release, 2026-10-21)**: the stipplefs payload (`1512eca`, `--payload stipple`, flag bit 9), `--prefer-cache` (`20f0e6c`, flag bit 8), the app's `argv[0]` becoming its tree path (`be446cc`). Release notes: `CHANGELOG.md`.
- **After 0.4.2, unreleased (HEAD `cd99efb`, 2026-10-22 to 2026-10-26)**: GLX vendor libraries farmed from the host (`1db8d66`), DRI module dependencies farmed (`1f12826`), integration of every entrypoint that has a menu entry (`08a39bd`, `crates/onelf-format/src/desktop.rs`), and direct-release delta self-updates replacing zsync (`cd99efb`, PR #41, with an explicit unsigned opt-in). Release PR #40 (0.4.3) was open on 2026-10-28.

---

## 10. Reality Check: Marketing Claims vs. Code Reality

| Claim in Docs / Site | Code Reality | Verdict |
|---|---|---|
| "Zero host dependencies" | True for the static musl runtime prefix; dynamic apps still depend on kernel user namespaces or SUID `fusermount3`, or on a writable exec-capable directory for the last rung. (`/dev/shm` appeared in the first edition; nothing in `crates/` or `docs/` uses it.) | **Verified with Nuance** |
| "No LD_LIBRARY_PATH pollution" | Verified in PR #31 (`1e5385e`). Linker is invoked with `--library-path`; host-only paths set only when bootstrap requires it. | **Verified** |
| "In-memory execution without disk extraction" | Only available for static single binaries or packages marked `memfd = true`. Standard multi-file packages use FUSE or tmpfs. | **Verified** |
| "Automatic host GPU acceleration" | Implemented via symbol version comparison (`verdef.rs`) and ephemeral link farm. Bundles no Mesa by default; a package that pins a GL build fetches it (BLAKE3-verified) when the host has no GL (`launch.rs:421-432`). Pinless packages on hosts with no GL still fail. | **Verified, corrected** |
| "Self-updating single binary" | Release 0.4.2: `zsync-rs` with Ed25519 signature checks (`update.rs` at tag `0.4.2`), needs `.zsync` and `.zsync.sig` on the server, a key embedded at pack time and `--update-revision` for rollback protection. HEAD: no control file, the URL names the binary, signature at `<url>.sig`, or an explicit unsigned opt-in (`update/mod.rs`, section 4.2). | **Verified in source for both; neither run** |
