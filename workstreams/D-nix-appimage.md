# Deep-Dive Technical Research: nix-appimage & Nix Closure Bundling

**Target Ecosystem:** `pkgforge/nix-appimage` (https://github.com/pkgforge/nix-appimage), `ralismark/nix-appimage`, `matthewbauer/nix-bundle`  
**Evidence Standard:** [verified] (code inspection), [reported] (issues/docs), [inferred] (architectural deduction).

---

## 1. Architecture and Mechanics

### 1.1 Closure Discovery and Assembly
In `nix-appimage`, the packaging pipeline traces dependencies using Nix pure evaluation (`flake.nix`, `mkAppImage.nix` [verified]):
1. **Transitive Closure:** Traced via `writeClosure [ program ]`. Nix derivations scan compiled binaries for the 32-character base-32 hashes of all other store paths.
2. **Two-Pass SquashFS Construction:**
   - First pass compresses all referenced store items under their original `/nix/store/<hash>-<name>` directory structure using `mksquashfs -no-strip -b 1M` [verified].
   - Second pass appends `AppRun`, `bwrap`, and runtime scripts to the root of the archive.
3. **Runtime Stub:** Prepends an AppImage Type 2 static runtime (`appimage-type2-runtime`, compiled with static musl, `squashfuse_ll`, and `libfuse3`) at offset 0 via `dd` [verified].

### 1.2 The Absolute Store Path Requirement
Every Nix-compiled dynamic binary has immutable absolute paths compiled into its ELF headers:
- `PT_INTERP`: `/nix/store/<hash>-glibc-<ver>/lib/ld-linux-x86-64.so.2` [verified].
- `DT_RUNPATH`: Points strictly to `/nix/store/<hash>-.../lib` [verified].

When the kernel loads an ELF (`fs/binfmt_elf.c`), it resolves `PT_INTERP` against the current root filesystem mount namespace. If `/nix/store` does not exist on the host, `execve()` fails immediately with `ENOENT`, regardless of `LD_LIBRARY_PATH`. Therefore, **virtualizing `/nix/store` at runtime is strictly mandatory**.

### 1.3 Namespace Containment Mechanisms
- **Bubblewrap (`pkgforge/nix-appimage`):** `AppRun.sh` executes bundled `bwrap` with `--ro-bind "$APPDIR/nix" /nix` [verified].
- **Custom userns-chroot (`ralismark/nix-appimage`):** A custom C stub calls `unshare(CLONE_NEWUSER | CLONE_NEWNS)`, creates a private tmpfs root, bind-mounts all host root directories except `/nix`, bind-mounts `$APPDIR/nix` to `/nix`, and calls `chroot()` [verified].
- **PRoot (`nix-bundle`):** Uses `ptrace` system call interception to rewrite path strings from `/nix` to a cache directory. Incurs severe CPU overhead and breaks under seccomp.

---

## 2. Inherent Failure Modes

### 2.1 Host Collision on NixOS
When run on a host that already has Nix installed (like NixOS or multi-user Nix on Ubuntu):
- The bundle bind-mounts its private `$APPDIR/nix` directly over `/nix` [verified].
- This completely shadows the host store. On NixOS, where all system utilities (including `/bin/sh`) reside in `/nix/store`, the application cannot invoke any host commands.
- `pkgforge/nix-appimage` prints an explicit warning: `WARNING: NixAppImage WILL NOT WORK (properly) on NixOS` (`AppRun.sh:144-146` [verified]).

### 2.2 Unprivileged User Namespace Restrictions
- If the host kernel restricts unprivileged user namespaces (`kernel.unprivileged_userns_clone = 0`, or Ubuntu 23.10/24.04 AppArmor restrictions), `nix-appimage` fails immediately with `cannot unshare: Operation not permitted` (exit code 127) [verified].
- It has no fallback mode (unlike `onelf` or `uruntime`). Extracting the AppImage does not resolve the issue, because executing `AppRun` still requires `bwrap`/`unshare`.

### 2.3 Broken Host GPU & OpenGL Acceleration
- Nix binaries do not look in `/usr/lib` or `/etc/ld.so.cache` for host GPU drivers (`ralismark/README.md:30` [verified]).
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
| **Size Overhead** | Extreme (full closures, 2–5x bloat) | Compact (custom zstd blocks, pruning) |
