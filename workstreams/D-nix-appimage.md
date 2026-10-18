# Deep-Dive Technical Research: nix-appimage & Nix Closure Bundling

**Target Ecosystem:** `pkgforge/nix-appimage` (https://github.com/pkgforge/nix-appimage), `ralismark/nix-appimage`, `matthewbauer/nix-bundle`  
**Evidence Standard:** [verified] (code inspection), [reported] (issues/docs), [inferred] (architectural deduction).  
**Upstream revisions re-verified this pass:** pkgforge/nix-appimage `b6e7dfc`, ralismark/nix-appimage `7946add`, matthewbauer/nix-bundle `eff0159`.

---

## 1. Architecture and Mechanics

### 1.1 Closure Discovery and Assembly
In `nix-appimage`, the packaging pipeline traces dependencies using Nix pure evaluation (`flake.nix`, `mkAppImage.nix` [verified]):
1. **Transitive Closure:** Traced via `writeClosure` in the pkgforge fork (`mkAppImage.nix:43`); upstream `ralismark` deliberately avoids `writeClosure` and uses `writeReferencesToFile` instead, a local re-implementation built on `exportReferencesGraph`, written as a workaround for a `writeClosure` bug (`mkAppImage.nix:28-54`, used at `:71`) [corrected attribution]. Nix derivations scan compiled binaries for the 32-character base-32 hashes of all other store paths.
2. **Two-Pass SquashFS Construction:**
   - First pass compresses all referenced store items under their original `/nix/store/<hash>-<name>` directory structure using `mksquashfs -b 1M -Xcompression-level 1` (pkgforge `mkAppImage.nix:27,29`) [verified; flags corrected - an earlier note claimed upstream uses neither `-no-strip` nor an explicit block size, which was half wrong: upstream ralismark also passes `-no-strip` in the first pass (`mkAppImage.nix:80`); what pkgforge adds over upstream is `-b 1M` and `-Xcompression-level 1`]
   - Second pass appends the AppRun to the root of the archive (pkgforge: the `AppRun.sh` script plus bundled `bwrap` binaries, `appruns/bwrap/default.nix`; ralismark: the compiled `userns-chroot` stub plus `.DirIcon`/desktop/icon extras, `mkAppImage.nix:86-87`).
3. **Runtime Stub:** Prepends an AppImage Type 2 static runtime (`appimage-type2-runtime`) at offset 0 via `dd` [verified; upgraded from [reported]: pkgforge `mkAppImage.nix:63` runs `dd if=<runtime> of=$out conv=notrunc` after both `mksquashfs` passes, with `-offset $(stat -L -c%s <runtime>)` (`mkAppImage.nix:25`) reserving the leading space; `runtimes/appimage-type2-runtime/default.nix` builds AppImage/type2-runtime rev `2df896e` with `-static` (line 74), links `-lsquashfuse -lsquashfuse_ll -lfuse3` (line 75), and patches in the `AI\x02` Type-2 magic bytes. The earlier "compiled with static musl" is dropped: no musl appears anywhere in the build files].

### 1.2 The Absolute Store Path Requirement
Every Nix-compiled dynamic binary has immutable absolute paths compiled into its ELF headers:
- `PT_INTERP`: `/nix/store/<hash>-glibc-<ver>/lib/ld-linux-x86-64.so.2` [verified].
- `DT_RUNPATH`: Points strictly to `/nix/store/<hash>-.../lib` [verified].

When the kernel loads an ELF (`fs/binfmt_elf.c`), it resolves `PT_INTERP` against the current root filesystem mount namespace. If `/nix/store` does not exist on the host, `execve()` fails immediately with `ENOENT`, regardless of `LD_LIBRARY_PATH`. Therefore, **virtualizing `/nix/store` at runtime is strictly mandatory**.

### 1.3 Namespace Containment Mechanisms
- **Bubblewrap (`pkgforge/nix-appimage`):** `AppRun.sh` executes bundled `bwrap` with `--ro-bind "${SELF_PATH}/nix" '/nix'` (`AppRun.sh:381`; `SELF_PATH`, set at `AppRun.sh:97`, is the directory of the resolved AppRun, i.e. the image root) [verified; re-checked at `b6e7dfc`, previously paraphrased as `--ro-bind "$APPDIR/nix" /nix`].
- **Custom userns-chroot (`ralismark/nix-appimage`):** A custom C stub calls `unshare(CLONE_NEWNS)` (plus `CLONE_NEWUSER` only when not running as root, `main.c:99-106`), creates a private tmpfs root, bind-mounts all host root directories except `/nix`, bind-mounts `$APPDIR/nix` to `/nix`, and calls `chroot()` (`appruns/userns-chroot/main.c` at ralismark `7946add`: `unshare` at line 106, the `$APPDIR/nix` bind mount at line 183 (mkdir at 182), `chroot` at line 195) [verified; line numbers corrected from ~182/~193].
- **nix-bundle:** Its primary mechanism is the vendored `nix-user-chroot` (`unshare` + `chroot`; `main.cpp:243`, `main.cpp:289`, re-checked at `eff0159`; the bundle startup script invokes it at `default.nix:134`, and the AppImage mode inlines the same logic in `AppRun.c:169/230`). A `proot` bootstrap is an alternative mode (`nix-bootstrap.sh:9-29`, which itself exports `PROOT_NO_SECCOMP=1` at line 10) that uses `ptrace` system call interception to rewrite `/nix` paths, incurring severe CPU overhead and breaking under seccomp [corrected: an earlier edition presented proot as nix-bundle's primary mechanism].

---

## 2. Inherent Failure Modes

### 2.1 Host Collision on NixOS
When run on a host that already has Nix installed (like NixOS or multi-user Nix on Ubuntu):
- The bundle bind-mounts its private `$APPDIR/nix` directly over `/nix` [verified].
- This completely shadows the host store. On NixOS, where all system utilities (including `/bin/sh`) reside in `/nix/store`, the application cannot invoke any host commands.
- `pkgforge/nix-appimage` prints an explicit warning: `WARNING: NixAppImage WILL NOT WORK (properly) on NixOS (You have /nix/store)` (`AppRun.sh:165` [line corrected]).

### 2.2 Unprivileged User Namespace Restrictions
- If the host kernel restricts unprivileged user namespaces (`kernel.unprivileged_userns_clone = 0`, or Ubuntu 23.10/24.04 AppArmor restrictions), `nix-appimage` fails immediately with `cannot unshare: Operation not permitted` (exit code 127) [verified in source, ralismark `7946add`: `#define EXIT_EXECERROR 127` at `main.c:25`, `exit(EXIT_EXECERROR)` in the `die_if` helper at `main.c:40`, failure site `main.c:106`; the previously cited `main.c:27-33` was wrong and holds the `argv0`/`appdir`/`mountroot` globals and the start of the `die_if` signature. The specific message and exit code are undocumented in the READMEs, though ralismark's `README.md:44` does warn that user namespaces "may not be enabled for security reasons"; pkgforge's bundle instead fails at the same step inside `bwrap`].
- It has no fallback mode (unlike `onelf` or `uruntime`). Extracting the AppImage does not resolve the issue, because executing `AppRun` still requires `bwrap`/`unshare`.

### 2.3 Broken Host GPU & OpenGL Acceleration
- Nix binaries do not look in `/usr/lib` or `/etc/ld.so.cache` for host GPU drivers (`ralismark/README.md:35` [line corrected]).
- When an application calls `dlopen("libGL.so")`, it either fails or falls back to software rendering (`llvmpipe`), because host Mesa and NVIDIA proprietary drivers are inaccessible.
- Running GPU apps requires wrapping the build with `nixGL`, which adds external dependencies and complexity.

---

## 3. Comparison with onelf

| Property | `nix-appimage` | `onelf` |
|---|---|---|
| **Reproducibility** | Mathematical bit-for-bit (`narHash`) | Recipe-based (subject to mirror drift) |
| **Relocatability** | Zero (hardcoded `/nix/store` paths) | Fully relocatable ($ORIGIN, link farm) |
| **Fallback Ladder** | None (crashes if userns blocked) | 6 tiers (memfd -> FUSE -> tmpfs -> rundir) |
| **GPU Acceleration** | Broken out-of-the-box (needs nixGL) | Automatic in-process superset resolver |
| **Size Overhead** | Extreme (full closures, 2–5x bloat [inferred; no upstream or onelf measurement states this figure]) | Compact (custom zstd blocks, pruning) |
