# Deep-Dive Technical Research: Anylinux-AppImages & Tooling Ecosystem

**Target Ecosystem:** `pkgforge-dev/Anylinux-AppImages` (https://github.com/pkgforge-dev/Anylinux-AppImages)  
**Tools Analyzed:** `quick-sharun.sh`, `pkgforge-dev/Anylinux-sharun`, `pkgforge-dev/appimagetool`, `VHSgunzo/uruntime`, `cross-libc-dlopen`  
**Evidence Standard:** [verified] (code/docs inspection), [reported] (issues/PRs/maintainer statements), [inferred] (architectural deduction).

---

## 1. Architecture and Packaging Pipeline

### 1.1 Tooling Landscape
Contrary to legacy AppImage tooling (`appimagetool`, `linuxdeploy`), the `Anylinux-AppImages` initiative relies on its own toolchain (it still shells out to `patchelf`, `ldd`, `xvfb-run` and the upstream `mkdwarfs`):
- **`quick-sharun.sh`** (`useful-tools/quick-sharun.sh` [verified]): A monolithic 170 KB POSIX shell orchestration script (replacing deprecated `uruntime2appimage.sh`) that manages dependency tracing, binary patching, and bundle layout assembly.
- **`Anylinux-sharun`** (`pkgforge-dev/Anylinux-sharun` [verified]): A specialized Rust fork of `VHSgunzo/sharun`. Multiplexes binaries in `$APPDIR/bin/*` via hard links to a single `sharun` binary.
- **`uruntime`** (`VHSgunzo/uruntime` [verified]): A static Rust runtime replacing AppImage `type2-runtime`. Supports DwarFS and SquashFS images. The pinned `appimagetool` 0.5.3 downloads release `v0.8.1` of the `uruntime-appimage-dwarfs-lite` variant and checks its SHA-256 (`appimagetool/src/pinned.rs`). Release assets are static musl builds (`uruntime/docs/BUILDING.md:7`); the `x86_64` `uruntime-appimage-dwarfs-lite` asset of `v0.8.1` is 1,507,016 bytes and the full `uruntime-appimage-x86_64` is 4,274,056 bytes (GitHub releases API, fetched on the date of this edit; the `x86_64` runtime only).
- **`pkgforge-dev/appimagetool`** (`pkgforge-dev/appimagetool` [verified]): A pure Rust tool that patches the runtime's ELF sections (`.upd_info` and `.envs`), invokes `mkdwarfs`, and generates `.zsync` files.

### 1.2 Closure Tracing
`quick-sharun.sh` implements two collectors [verified]: `_lib4bin_collect_ldd` (line 1669; one `ldd` pass per input plus a `patchelf --print-needed` cross-check - a single pass, not recursive) and `_lib4bin_collect_strace` (lines 1728-1815), which runs each target under `LD_DEBUG=libs` for `STRACE_TIME` seconds (default 5, under `xvfb-run` when available) and then kills it, so it only catches `dlopen()` calls made inside that window. `STRACE_MODE` defaults to 1 (`quick-sharun.sh:61`); `STRACE_MODE=0` turns it off. The script executes the targets on the build host, which must have the application installed in `/usr`; its header says deploying on any system other than Arch Linux is "a VERY BAD IDEA" (`quick-sharun.sh:25`). It stages the resolved `.so` files into `$APPDIR/lib` (`$APPDIR/shared/lib` is a compatibility symlink to it). [Corrected: an earlier edition called the ldd sweep recursive and strace-based.]

---

## 2. Libc Handling and Kernel Portability

### 2.1 Complete Glibc Bundling
- Bundles the current Arch glibc and dynamic linker (`ld-linux-x86-64.so.2`) into `$APPDIR/lib` [corrected: an earlier edition claimed "glibc 2.40 to 2.44", which no file in the repo states; the bundled version is whatever the Arch build image provides, and Arch glibc is built with `--enable-kernel=4.4` per FAQ.md].
- Bypasses host glibc completely: passes `--library-path` directly to the bundled dynamic linker.
- Maps dynamically linked 64-bit application binaries via **`userland-execve`**, so `/proc/self/exe` keeps pointing at `bin/<app>` (the `sharun` hard link) rather than `ld-linux.so` (`Anylinux-sharun/src/main.rs:482`; upstream `userland-execve-rust` README). Static binaries, 32-bit binaries and Bun/patched binaries take other paths (`main.rs:438-479`): static ones use a plain `exec`, 32-bit ones a real `exec` of the bundled interpreter, and patched ones a copy of the interpreter in `/tmp`.

### 2.2 Host Isolation & Preload Defense
- Patches the bundled dynamic linker binary in-place:
  `sed -i -e 's|/etc|/KEK|g' "$APPDIR/lib/ld-linux-x86-64.so.2"` [verified; the script applies it to every staged `ld-linux*.so*`/`ld-musl*.so*` containing the string, at `quick-sharun.sh:4899-4905`].
- This prevents the dynamic linker from reading host `/etc/ld.so.preload` and `/etc/ld.so.cache`. Upstream's stated reason is that reading `/etc/ld.so.cache` "would segfault instantly on some systems" (`HALL-OF-FAME.md:105`); an earlier commit (`2501024`) patched only `/etc/ld.so.preload`. No upstream file ranks this as the most common crash cause, and none was measured here.

### 2.3 Old Kernel Compatibility Layer (Down to Linux 2.6.17)
`Anylinux-sharun` embeds a kernel syscall emulation layer (`kernel_compat.rs`, `emulated_syscalls.rs` [verified]):
- Uses `ptrace` and `seccomp` to intercept missing system calls when running on older kernels. The layer is `x86_64` only (`kernel_compat.rs:17,20`, `#![cfg(target_arch = "x86_64")]`). It turns on automatically only on kernels older than 4.0 or when `statx` is missing, and `SHARUN_OLD_KERNEL_COMPAT=1/0` forces it. With seccomp-bpf (3.5+) only the affected syscalls trap; on older kernels every syscall is ptraced, which upstream calls "much slower".
- Emulates: `statx` (Linux 4.11+), `futex_wait_bitset` (Linux 2.6.25+), `epoll_pwait` (Linux 2.6.19+), `getrandom` (Linux 3.17+), `pipe2` (Linux 2.6.27+), `prlimit64` (Linux 2.6.36+), and `XGETBV` processor instructions, among others (the README also lists `ppoll`, `epoll_create1`, `preadv`/`pwritev`, `eventfd`, `timerfd`, termios2 ioctls and newer clock ids).
- Allows modern glibc binaries - the README's example is the `--enable-kernel=4.4` Arch build - to execute on kernels far older than that glibc assumes, down to Linux 2.6.17 (`Anylinux-sharun/README.md`; FAQ.md: "Short answer: 2.6.17"; the README says kernels older than 2.6.16 cannot work because the runtime needs the `*at` syscalls) [inferred: the CentOS 6 (2.6.32), RHEL 5 (2.6.18) and RHEL 6 (2.6.32) kernels sit above that floor, but no upstream document names these distros].

---

## 3. Host Integration: GPU, Wayland, and Desktop

### 3.1 GPU Driver Interoperability
- **Default (Bundled Mesa):** Bundles debloated Mesa (stripped of LLVM and non-essential drivers) directly inside the AppImage [corrected: the "20-35 MB" figure in an earlier edition is not a repo number; `HOW-TO-MAKE-THESE.md` documents whole-AppImage results under 35 MiB].
- **Experimental (Host Drivers):** When `USE_HOST_DRIVERS_EXPERIMENTAL=1`, `cross-libc-dlopen.so` interposes `dlopen()`. It parses the host driver's ELF headers and loads a rewritten private copy: the `DT_VERSYM`, `DT_VERNEED`, `DT_VERDEF` and `DT_VERDEFNUM` dynamic tags are replaced with the ignored tag `CLD_NEUTRAL_TAG` (`cross-libc-dlopen.c:69,810-816`), and `DT_NEEDED` edges that would pull in musl libc are neutralised the same way (`:1871`) [verified]. Forwarding shims (`gl-fwd.so`, `egl-fwd.so`, `gles-fwd.so`) are built with the SONAME of the library they replace and forward entry points to whatever the host provides, for hosts whose OpenGL/EGL/GLES set is incomplete or lacks GLVND (`cross-libc-dlopen/README.md:36-49`). The mode is refused for 32-bit and SDL applications, and upstream's own help text says not to use it with emulators (`quick-sharun.sh:379,573,996`).
- **NVIDIA Proprietary:** Probes `/sys/module/nvidia/version` and dynamically adds host driver directories to `LIBVA_DRIVERS_PATH` (`/run/opengl-driver/lib/dri`, `/usr/lib/dri`, `/usr/lib64/dri`, multiarch `dri`) and `GBM_BACKENDS_PATH` (the same pattern with `gbm`) (`set_appdir_env.rs:112-128`), orders the NVIDIA EGL vendor JSON first in `__EGL_VENDOR_LIBRARY_FILENAMES` when that variable is unset (`:455-480`), and appends host NVIDIA Vulkan ICDs to `VK_DRIVER_FILES` unless `SHARUN_ALLOW_SYS_VKICD=0` (`:487-520`). `SHARUN_NO_NVIDIA_EGL_PRIME=1` disables the first two [verified; `Anylinux-sharun/src/set_appdir_env.rs`]. These are driver-plugin search paths, not general library paths.

### 3.2 Desktop & Environment Sanitization
- **`gtk-fix-nonsense.so`:** Forces the Wayland window class/app-id to the value of `$GTK_WINDOW_CLASS` (fixing desktop integration) and remaps `/usr` prefixes so bundled typelibs are found instead of host ones [verified; `Anylinux-sharun/lib/gtk-fix-nonsense.c`].
- **`glycin-fix.so`:** Disables the bwrap sandbox of GNOME's glycin image loader, which does not work inside an AppImage [verified; `Anylinux-sharun/README.md`].
- **`anylinux.so`:** Interposes `execve`, `execv`, `execvp`, `execvpe`, `posix_spawn` and `posix_spawnp` (`anylinux.c:506-552`) to unset a list of 61 loader and bundled-path variables (`ALSA_CONFIG_PATH`, `LD_PRELOAD`, `QT_PLUGIN_PATH`, ...) before spawning a process whose path lies outside `$APPDIR`, so host applications do not inherit the bundle's settings [verified].

---

## 4. Runtime, Compression, and Startup Mechanics

- **DwarFS Filesystem:** Employs DwarFS with Zstandard compression, default `-C zstd:level=22 -S26 -B2` (`appimagetool/src/config.rs:175`, tag `0.5.3` = main `a9f5ebf`; the string also appears in a comment at `src/dwarfs.rs:104`). `zstd:level=5 -S19` (`src/dwarfs.rs:149-151`) is used only for the throwaway OPTIMIZE_LAUNCH profiling image. `-S26` means 2^26-byte (64 MiB) blocks and `-B2` means a scan of the 2 most recent blocks for duplicate segments (mkdwarfs manual); whole-file deduplication is separate and on by default (`--file-hash`). So segment deduplication is bounded by that lookback window, not global. Upstream states that DwarFS is "a lot faster than SquashFS while being smaller at the same time" (`FAQ.md:144`) and "many times faster than SquashFS" (`HOW-TO-MAKE-THESE.md:158`). No percentage appears in the text of the tooling repos (`FAQ.md:146` embeds a screenshot that was not inspected), and nothing was measured here [reported].
- **Profile-Guided Launch Optimization (`OPTIMIZE_LAUNCH=1`):** Analyzes block access patterns during startup and groups blocks by hotness (`--categorize=hotness` is passed by `appimagetool/src/dwarfs.rs:99`; the feature is documented at `HOW-TO-MAKE-THESE.md:158`); "In many cases, launch times are near-identical to those of native applications (+/-300 ms on a system with a 2016 CPU)" is their reported figure (`HOW-TO-MAKE-THESE.md:158`), not measured here.
- **3-Tier Execution Fallback:**
  1. Direct FUSE mount via embedded `squashfuse` / `dwarfs` helpers.
  2. Unprivileged user & mount namespaces (`unshare`).
  3. Automatic extract-and-run when mounts fail. With the default `URUNTIME_EXTRACT=3` this applies only if the whole file is no larger than 350 MiB (`uruntime/docs/CONFIGURATION.md:18-25`); `--appimage-mount` never falls back to extraction.
- **Mount Reuse via OFD Locks:** Uses Open File Description locks (`F_OFD_SETLK`, `uruntime/src/main.rs:2076-2078`) to coordinate shared mounts and extracted directories across overlapping launches (a shared lifetime lease, an exclusive lease for cleanup). Kernels before Linux 3.15 and filesystems without OFD support use a `flock` backend (`docs/CONFIGURATION.md:46`).

---

## 5. Maintainer Pain Points

1. **Host dynamic-linker reads of `/etc`:** the `ld.so.cache` segfault (and, originally, `ld.so.preload`) is avoided by `/etc` -> `/KEK` patching (see 2.2).
2. **Fontconfig binary cache incompatibility:** Mismatched cache formats crash applications; resolved by re-pointing `XDG_CACHE_HOME` to an isolated `AppImage-Cache` directory (`quick-sharun.sh:4018-4030`; `HALL-OF-FAME.md:91-97`; their issue #657, "Strange behavior of fontconfig", closed).
3. **Ubuntu 24.04 Unprivileged Namespace Restrictions:** Mitigated by the opt-in `fix-namespaces.hook` (added with `ADD_HOOKS=fix-namespaces.hook`), which on AppArmor hosts asks the user for elevation (`pkexec`, `lxqt-sudo` or `run0`, via `run_gui_sudo`, `quick-sharun.sh:4062-4078`) and writes a persistent `/etc/sysctl.d/20-fix-namespaces.conf` setting `kernel.apparmor_restrict_unprivileged_userns = 0`; on secureblue it runs `ujust set-unconfined-userns on`; elsewhere it only shows a message (`quick-sharun.sh:2268-2345`).
4. **Maintenance Overhead:** The 5,199-line `quick-sharun.sh` shell script contains extensive heuristic workarounds for edge cases, requiring constant maintenance.

---

## 6. Direct Comparison: onelf vs. Anylinux-AppImages

| Feature | `onelf` | `Anylinux-AppImages` |
|---|---|---|
| **Build Architecture** | Declarative `onelf.toml` + pure Rust CLI | Imperative 170 KB POSIX shell script (`quick-sharun.sh`) |
| **Kernel Floor** | Linux 3.17+ (`memfd`) / 3.8+ (`userns`) [inferred from syscall usage] | Linux 2.6.17+ on `x86_64` only (via ptrace/seccomp syscall emulation; automatic only on kernels older than 4.0) |
| **Compression** | 64 KiB zstd blocks | DwarFS (zstd:level=22, -S26 -B2 default, whole-file dedup plus segment dedup over a 2-block lookback) |
| **In-Memory Exec** | Native `memfd_create` for static single binaries only (latency not measured) | Not supported for the payload (requires mount or extract); `uruntime` itself runs its embedded helper tools through `memfd` |
| **GPU Approach** | Symbol-version superset match into host | Bundled debloated Mesa or `cross-libc-dlopen` |
| **Security/Integrity** | Signed updates (Ed25519) | No GPG in the toolchain (one comment in `make-aur-package.sh`); `uruntime` can embed a `.sha256_sig` section but only prints or writes it (`uruntime/src/main.rs:4636-4650`), it never verifies it at launch; `appimagetool` SHA-256-checks its pinned `uruntime` and `mkdwarfs` downloads (`src/pinned.rs`, `src/util.rs:84-169`); that protects build inputs, not the shipped AppImage |
