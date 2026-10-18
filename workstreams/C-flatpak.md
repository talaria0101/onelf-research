# Deep-Dive Technical Research: Flatpak vs. Single-File Bundles (onelf)

**Target Ecosystem:** Flatpak (https://github.com/flatpak/flatpak, https://github.com/flatpak/flatpak-builder)  
**Evidence Standard:** [verified] (source code inspection), [reported] (issues/benchmarks/docs), [inferred] (architectural deduction).
**Second-pass fact-check (2026-10-18):** citations and claims re-verified against flatpak main `ed564f7` and xdg-dbus-proxy `0.1.9` (`72b40c8`); corrections noted inline.

---

## 1. Flatpak Architecture Overview

### 1.1 OSTree Storage Model
Flatpak is built on **OSTree** operating in `OSTREE_REPO_MODE_BARE_USER_ONLY` (`flatpak/common/flatpak-dir.c:5023` [verified]; the adjacent comment exempts old installations that still use `bare-user`). 
- When an application or runtime is installed, files are checked out as **POSIX hard links** pointing directly into the content-addressed object store (deploy checkout at `flatpak-dir.c:10134-10168`; appstream checkout block at `flatpak-dir.c:5689-5694`, same pattern) [verified, range corrected; re-checked at flatpak main `ed564f7`].
- Applications sharing identical files (e.g. standard runtime libraries, icons, fonts) consume zero additional disk space.
- The Linux kernel page cache indexes memory pages by `(device, inode)`. Because files are hardlinked to identical inodes on disk, multiple running Flatpak applications share physical RAM pages for identical libraries [verified; kernel mechanism re-demonstrated on the checking machine: two hard links to one inode, faulting all pages in through one name leaves every page resident under the other (mincore 0 -> 8192/8192 for a 32 MiB file; re-confirmed with an mmap fault path, since on ZFS plain read() populates the ARC, not the page cache)].

### 1.2 Runtimes & Extensions
- Applications build against standardized runtimes (`org.freedesktop.Platform`, `org.gnome.Platform`, `org.kde.Platform`).
- Runtime branches have bounded support windows before EOL, and they are not uniform: Freedesktop branches get a 2-year support period; GNOME branches are usually supported about a year and EOL'd at the next stable release (Flathub and flatpak runtime docs) [reported]. Flathub marks applications on EOL runtimes as deprecated, and `flatpak update` surfaces end-of-life warnings [reported].
- Hardware-specific drivers are mounted dynamically via extension points (e.g. `flatpak_get_gl_drivers`, `flatpak-utils.c:517`, matches `/sys/module/nvidia/version` with dots stripped to dashes into `org.freedesktop.Platform.GL.nvidia-<ver>`; the extension binds under `/usr/<directory>` from the extension's declared directory, `/usr/lib/x86_64-linux-gnu/GL` for the freedesktop GL extension, via `flatpak_run_add_extension_args`, `flatpak-run.c:128`) [verified].

### 1.3 Bubblewrap (`bwrap`) Sandboxing & Seccomp
Flatpak constructs an isolated container using Bubblewrap (`flatpak-run.c:3656` [verified]):
- Mounts runtime at `/usr` (`--ro-bind-fd runtime_fd /usr`) and app at `/app` (`--ro-bind-fd app_fd /app`).
- Unshares user namespaces (`--unshare-user` + `--disable-userns`, `flatpak-run.c:2395-2396`), PID namespaces (`--unshare-pid`, `flatpak-run.c:2429`), and network namespaces (`--unshare-net`, `flatpak-run.c:410`, applied only when the app metadata does not grant `shared=network`) [verified].
- Implements strict Seccomp-BPF filters (`flatpak-run.c:2013-2110` blocklist [verified, range corrected]): blocks terminal injection (`TIOCSTI`/`TIOCLINUX`), `clone3` (returns `ENOSYS` so glibc falls back to `clone`, per the in-code CVE-2021-41133 comment), `syslog`, `keyctl`, and restricts socket domains to `AF_UNSPEC`, `AF_LOCAL`, `AF_INET`, `AF_INET6`, and `AF_NETLINK` (plus flag-gated `AF_CAN`/`AF_BLUETOOTH`).

### 1.4 Portals and D-Bus Mediation
- By default, host D-Bus access is proxied through `xdg-dbus-proxy` (built from the `xdg-dbus-proxy` subproject, a wrap-git pin to 0.1.9 / `72b40c8` in `subprojects/dbus-proxy.wrap`). An explicit `--socket=session-bus`/`--socket=system-bus` instead bind-mounts the real bus socket and bypasses the proxy entirely [nuance added].
- Host file access is mediated via `org.freedesktop.portal.FileChooser` and `xdg-document-portal`, which exposes selected files via a virtual FUSE mount at `/run/flatpak/doc/` [verified].

### 1.5 Single-File `.flatpak` Bundles
Created via `flatpak build-bundle` (`flatpak-builtins-build-bundle.c` [verified]):
- Structure: A GVariant metadata header (magic `0xe5890001`, written at `flatpak-builtins-build-bundle.c:252`) followed by an OSTree static delta payload [verified].
- **Cannot be run standalone:** It is not an ELF executable. Running `chmod +x app.flatpak && ./app.flatpak` fails with `Exec format error`. It must be installed into the local OSTree repository via `flatpak install` [verified].

---

## 2. What Flatpak Does Fundamentally Better

1. **Least Privilege & Security Boundaries:** Confines applications to isolated namespaces. Protects `~/.ssh`, browser profiles, and host IPC from compromised dependencies [verified].
2. **Cross-Application Disk Deduplication:** 50 Flatpak apps sharing a 1.5 GB GNOME runtime consume ~3.5 GB total on disk, whereas 50 standalone bundles consume 25 to 50 GB [reported; inferred: the range holds only if each bundle stores the runtime compressed (~0.5-1 GB each), since 50 uncompressed 1.5 GB runtimes would exceed 75 GB].
3. **RAM Page Cache Sharing:** Hardlinked inodes in the OSTree store enable the kernel to share memory pages across different running applications [verified].
4. **Centralized Security Updates:** Patching the Freedesktop runtime immediately remediates critical CVEs (glibc, OpenSSL, libxml2) across all installed applications without requiring individual app rebuilds [reported].
5. **Desktop & App Store Integration:** Seamless native integration into GNOME Software and KDE Discover [reported].

---

## 3. Inherent Limitations of Flatpak

1. **Host Dependency & Tight Coupling:** Requires Bubblewrap usable unprivileged (`flatpak_bwrap_is_unprivileged`, `flatpak-utils.c:662`: bwrap present and not setuid) plus unprivileged user-namespace support in the kernel. A systemd user session is not strictly required: the transient-unit cgroup tracking that opens `/run/user/$UID/systemd/private` (`flatpak-run.c:987`) fails soft, and its caller continues: "We still run along even if we don't get a cgroup, as nothing really depends on it" (`flatpak-run.c:638-645`) [verified; requirement corrected]. D-Bus is needed for portals and bus proxies; with no session bus the app still runs, just without bus access [inferred]. Minimal containers that block `clone(CLONE_NEWUSER)` (Docker's default seccomp profile does) or that ship no bwrap cannot run Flatpak apps [reported].
2. **No-Install / Standalone Impossibility:** Cannot run directly from a USB flash drive or arbitrary directory without local installation [verified].
3. **Severe CLI / Pipeline Friction:** The sandbox environment is the host environment minus a fixed unset blocklist (`LD_PRELOAD`, `LD_LIBRARY_PATH`, `TMPDIR`, `XDG_RUNTIME_DIR`, `PYTHONPATH`, ...; `default_exports` handling at `flatpak-run.c:664-746`), with a full strip only under `flatpak run --clear-env` (`--clearenv` added by `flatpak_run_apply_env_clear`, `flatpak-run.c:849`, on `FLATPAK_RUN_FLAG_CLEAR_ENV` set at `flatpak-builtins-run.c:414`; corrected: an earlier edition named `--clean-env` and `flatpak_bwrap_empty_env`, the wrong flag and the wrong mechanism). Relative paths break because there is no CWD translation: `--chdir` is passed only for an explicit `--cwd` (`flatpak-run.c:3930-3931`), and nothing binds the caller's working directory into the sandbox [verified]. The commonly cited 50–200 ms container startup latency is [estimate, never measured]; the CLI-tool friction verdict itself stands [reported].
4. **First-App Download Penalty:** Installing a 10 MB utility requires pulling a 700 MB–1.5 GB base runtime [reported].
5. **Portal Friction & Path Rewriting:** Document portal virtual paths (`/run/flatpak/doc/...`) break applications that pass file paths to compilers, audio DAWs, or external tools [reported].

---

## 4. Takeaways for onelf

- **Opt-in Unprivileged Sandboxing:** `onelf-rt` can apply Landlock LSM (Linux 5.13+) filesystem isolation and Seccomp-BPF filters directly before `execve`, achieving Flatpak-grade containment without Bubblewrap or root.
- **CAS Hardlink Cache:** Implement an opt-in user cache (`~/.cache/onelf/cas/`) for extracted or cached binaries to share disk blocks and memory pages across multiple `onelf` applications.
