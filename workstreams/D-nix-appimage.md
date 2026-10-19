# Deep-Dive Technical Research: nix-appimage & Nix Closure Bundling

**Target Ecosystem:** `pkgforge/nix-appimage` (https://github.com/pkgforge/nix-appimage), `ralismark/nix-appimage`, `matthewbauer/nix-bundle`  
**Evidence Standard:** [verified] (code inspection), [reported] (issues/docs), [inferred] (architectural deduction).  
**Upstream revisions re-verified this pass:** pkgforge/nix-appimage `b6e7dfc`, ralismark/nix-appimage `7946add`, matthewbauer/nix-bundle `eff0159`.

---

## 1. Architecture and Mechanics

### 1.1 Closure Discovery and Assembly
In `nix-appimage`, the packaging pipeline traces dependencies from the Nix store reference graph at build time (`flake.nix`, `mkAppImage.nix` [verified]):
1. **Transitive Closure:** Traced via `writeClosure` in the pkgforge fork (`mkAppImage.nix:43`); upstream `ralismark` deliberately avoids `writeClosure` and uses `writeReferencesToFile` instead, a local re-implementation built on `exportReferencesGraph`, written as a workaround for a `writeClosure` bug (`mkAppImage.nix:28-54`, used at `:71`) [corrected attribution]. Nix derivations scan compiled binaries for the 32-character base-32 hashes of all other store paths.
2. **Two-Pass SquashFS Construction:**
   - First pass compresses all referenced store items under their original `/nix/store/<hash>-<name>` directory structure using `mksquashfs -b 1M -Xcompression-level 1` (pkgforge `mkAppImage.nix:27,29`) [verified; both forks pass `-no-strip` in the first pass (pkgforge `mkAppImage.nix:51`, ralismark `mkAppImage.nix:80`). Upstream ralismark's shared flags are only `-offset` and `-all-root` (`mkAppImage.nix:23-26`). pkgforge adds `-b 1M` (`:27`), `-no-xattrs` (`:28`) and `-Xcompression-level 1` (`:29`) to both passes via `commonArgs`. No `-comp` is given in either fork, so mksquashfs uses its default compressor, gzip (mksquashfs(1): "gzip (default)", `-Xcompression-level` 1..9, default 9) [inferred from the man page, no image was built]. pkgforge's own comment on `:29` is "We repack it later anyway"; the fast level 1 is therefore a build-time choice, not a size-optimised one]
   - Second pass appends the AppRun to the root of the archive (pkgforge: the `AppRun.sh` script plus bundled `bwrap` binaries, `appruns/bwrap/default.nix`; ralismark: the compiled `userns-chroot` stub plus `.DirIcon`/desktop/icon extras, `mkAppImage.nix:86-87`).
3. **Runtime Stub:** Prepends an AppImage Type 2 static runtime (`appimage-type2-runtime`) at offset 0 via `dd` [verified; upgraded from [reported]: pkgforge `mkAppImage.nix:63` runs `dd if=<runtime> of=$out conv=notrunc` after both `mksquashfs` passes, with `-offset $(stat -L -c%s <runtime>)` (`mkAppImage.nix:25`) reserving the leading space; `runtimes/appimage-type2-runtime/default.nix` builds AppImage/type2-runtime rev `2df896e` with `-static` (line 74), links `-lsquashfuse -lsquashfuse_ll -lfuse3` (line 75), and patches in the `AI\x02` Type-2 magic bytes. The earlier "compiled with static musl" is dropped: no musl appears anywhere in the build files].

### 1.2 The Absolute Store Path Requirement
Dynamic binaries built by nixpkgs have absolute store paths compiled into their ELF headers [general Nix behaviour; not re-checked against a binary in this pass]:
- `PT_INTERP`: `/nix/store/<hash>-glibc-<ver>/lib/ld-linux-x86-64.so.2` [reported].
- `DT_RUNPATH` (or `DT_RPATH`): points into `/nix/store/<hash>-.../lib` [reported].

When the kernel loads an ELF (`fs/binfmt_elf.c`), it resolves `PT_INTERP` against the current root filesystem mount namespace. If `/nix/store` does not exist on the host, `execve()` fails immediately with `ENOENT`, regardless of `LD_LIBRARY_PATH`. Therefore, for unmodified Nix binaries, **virtualizing `/nix/store` at runtime is mandatory**. Rewriting the interpreter and search paths at pack time is the alternative route (onelf takes it, with a length-preserving loader patch in `bundle/elf.rs`), at the cost of modifying the binaries.

### 1.3 Namespace Containment Mechanisms
- **Bubblewrap (`pkgforge/nix-appimage`):** `AppRun.sh` executes bundled `bwrap` with `--ro-bind "${SELF_PATH}/nix" '/nix'` (`AppRun.sh:381`; `SELF_PATH`, set at `AppRun.sh:97`, is the directory of the resolved AppRun, i.e. the image root) [verified; re-checked at `b6e7dfc`, previously paraphrased as `--ro-bind "$APPDIR/nix" /nix`].
- **Custom userns-chroot (`ralismark/nix-appimage`):** A custom C stub calls `unshare(CLONE_NEWNS)` (plus `CLONE_NEWUSER` only when not running as root, `main.c:99-106`), creates a private tmpfs root, bind-mounts all host root directories except `/nix`, bind-mounts `$APPDIR/nix` to `/nix`, and calls `chroot()` (`appruns/userns-chroot/main.c` at ralismark `7946add`: `unshare` at line 106, the `$APPDIR/nix` bind mount at line 183 (mkdir at 182), `chroot` at line 195) [verified; line numbers corrected from ~182/~193].
- **nix-bundle:** Its primary mechanism is the vendored `nix-user-chroot` (`unshare` + `chroot`; `main.cpp:243`, `main.cpp:289`, re-checked at `eff0159`; the bundle startup script invokes it at `default.nix:134`, and the AppImage mode inlines the same logic in `AppRun.c:169/230`). The repository also ships `nix-bootstrap.sh` and a `proot-x86_64` binary. The script (`nix-bootstrap.sh:9-29`, exports `PROOT_NO_SECCOMP=1` at line 10) installs Nix into `$HOME/.nix` and runs commands under `proot -b "$nixdir:/nix"`; it is a standalone script that nothing else in the repository invokes (`nix-bundle.sh` selects only the `nix-bootstrap*` Nix functions in `default.nix`, which use `nix-user-chroot`), and it was last changed in 2020 (`git log`, commit `5672912`) [verified at `eff0159`]. proot rewrites paths by `ptrace` system-call interception; the script disables proot's seccomp acceleration, so every syscall is traced. The CPU cost is not measured here [inferred]; "breaking under seccomp" is not supported by anything in the repository.

---

## 2. Inherent Failure Modes

### 2.1 Host Collision on NixOS
When run on a host that already has Nix installed (like NixOS or multi-user Nix on Ubuntu):
- The bundle runs the app in a new mount namespace whose root is built without the host `/nix`, and bind-mounts its private `$APPDIR/nix` at `/nix` there (ralismark: tmpfs root, all host root entries bound except `nix`, `main.c:128-183`; pkgforge: `bwrap` builds an empty root and `--ro-bind "${SELF_PATH}/nix" '/nix'`, `AppRun.sh:381`) [verified].
- The host store is therefore not visible to the app. On NixOS, where all system utilities (including `/bin/sh`) reside in `/nix/store`, the application cannot invoke any host commands.
- `pkgforge/nix-appimage` prints an explicit warning whenever `/nix/store` exists on the host (any Nix install, not only NixOS): `WARNING: NixAppImage WILL NOT WORK (properly) on NixOS (You have /nix/store)` (`AppRun.sh:165` [line corrected]).

### 2.2 Unprivileged User Namespace Restrictions
- If the host kernel restricts unprivileged user namespaces (`kernel.unprivileged_userns_clone = 0`, or Ubuntu 23.10/24.04 AppArmor restrictions), `nix-appimage` fails immediately with `<argv0>: cannot unshare: Operation not permitted` (exit code 127) [also observed: the stub compiled from `main.c` and run in this sandbox, where `unshare -Ur true` fails with EPERM, printed `/workspace/scratch/ulc: cannot unshare: Operation not permitted` and exited 127; this covers the ralismark stub only] [verified in source, ralismark `7946add`: `#define EXIT_EXECERROR 127` at `main.c:25`, `exit(EXIT_EXECERROR)` in the `die_if` helper at `main.c:40`, failure site `main.c:106`; the previously cited `main.c:27-33` was wrong and holds the `argv0`/`appdir`/`mountroot` globals and the start of the `die_if` signature. The specific message and exit code are undocumented in the READMEs, though ralismark's `README.md:44` does warn that user namespaces "may not be enabled for security reasons"; pkgforge's bundle instead fails at the same step inside `bwrap`].
- It has no fallback mode (unlike `onelf`, and unlike `uruntime` per the Anylinux-AppImages README [reported], which says it falls back to namespaces and then to extract-and-run). pkgforge's `AppRun.sh` runs `bwrap_run || true` and ends with an `echo`, so a failed `bwrap` still gives the AppImage an exit status of 0 (`AppRun.sh:410-421`, read not run). Extracting the AppImage does not resolve the issue, because executing `AppRun` still requires `bwrap`/`unshare`.

### 2.3 Broken Host GPU & OpenGL Acceleration
- OpenGL apps are documented as unable to run on non-NixOS hosts (`ralismark/README.md:35`, which links nixpkgs#9415 and ralismark/nix-appimage#5 and calls it out of scope). The mechanism offered here, that Nix-built glibc binaries do not search `/usr/lib` or `/etc/ld.so.cache` for host drivers, is [inferred]; the README does not state it. pkgforge's `bwrap` root binds no `/usr/lib` or `/lib` libraries; the only host paths bound are `/run`, `/tmp`, `/sys`, a few `/etc` files, `/lib/firmware`, `/usr/share/{fonts,fontconfig,icons,locale,themes}` and the optional `SHARE_*`, `/dev` and `$HOME` binds (`AppRun.sh:375-396`) [verified, read not run].
- When an application calls `dlopen("libGL.so")`, it either fails or falls back to software rendering (`llvmpipe`), because host Mesa and NVIDIA proprietary drivers are not found [inferred].
- The README's suggested remedy is "something like nixGL" (`ralismark/README.md:36`), an external dependency.

---

## 3. Comparison with onelf

| Property | `nix-appimage` | `onelf` |
|---|---|---|
| **Reproducibility** | Inputs pinned by `flake.lock` and `fetchurl` hashes (Nix input-addressed build); bit-for-bit equality of the final AppImage is not measured here [inferred] | Byte-identical output for identical input given `SOURCE_DATE_EPOCH` or `--mtime`; a `[sysroot]` recipe build pinned by archive hash is reproducible from archive plus recipe (`docs/guide/reproducible.md`); only pinless sysroot flows depend on mirror state |
| **Relocatability** | The AppImage file moves freely, but the closure inside keeps hardcoded `/nix/store` paths and needs `/nix` virtualized at run time (section 1.2) | Bundled libraries are found relative to the package ($ORIGIN, link farm) |
| **Fallback Ladder** | None for the userns/bwrap step (fails if user namespaces are blocked) | 6 rungs: memfd, userns+FUSE, fusermount3+FUSE, userns+tmpfs, runtime dir, persistent cache (the last only on request) (`docs/guide/execution-modes.md`) |
| **GPU Acceleration** | Broken out-of-the-box (needs nixGL) | Automatic in-process superset resolver |
| **Size Overhead** | Large: full closures plus gzip level 1 squashfs (see 1.1; "2-5x" is an unmeasured [estimate], no upstream or onelf source states it) | Compact (custom zstd blocks, pruning) |
