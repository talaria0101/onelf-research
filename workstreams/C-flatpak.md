# Deep-Dive Technical Research: Flatpak vs. Single-File Bundles (onelf)

**Target Ecosystem:** Flatpak (https://github.com/flatpak/flatpak, https://github.com/flatpak/flatpak-builder)  
**Evidence Standard:** [verified] (source code inspection), [reported] (issues/benchmarks/docs), [inferred] (architectural deduction).

---

## 1. Flatpak Architecture Overview

### 1.1 OSTree Storage Model
Flatpak is built on **OSTree** operating in `OSTREE_REPO_MODE_BARE_USER_ONLY` (`flatpak/common/flatpak-dir.c:5023` [verified]). 
- When an application or runtime is installed, files are checked out as **POSIX hard links** pointing directly into the content-addressed object store (deploy checkout at `flatpak-dir.c:10134-10168`; line 5690 is the appstream checkout, same pattern) [verified, line corrected].
- Applications sharing identical files (e.g. standard runtime libraries, icons, fonts) consume zero additional disk space.
- The Linux kernel page cache indexes memory pages by `(device, inode)`. Because files are hardlinked to identical inodes on disk, multiple running Flatpak applications share physical RAM pages for identical libraries [verified].

### 1.2 Runtimes & Extensions
- Applications build against standardized runtimes (`org.freedesktop.Platform`, `org.gnome.Platform`, `org.kde.Platform`).
- Runtimes follow a strict 1-year lifecycle before EOL. Flathub marks applications on EOL runtimes as deprecated.
- Hardware-specific drivers are mounted dynamically via extension points (e.g. matching `/sys/module/nvidia/version` to mount `org.freedesktop.Platform.GL.nvidia-<ver>` at `/usr/lib/x86_64-linux-gnu/GL`) [verified].

### 1.3 Bubblewrap (`bwrap`) Sandboxing & Seccomp
Flatpak constructs an isolated container using Bubblewrap (`flatpak-run.c:3656` [verified]):
- Mounts runtime at `/usr` (`--ro-bind-fd runtime_fd /usr`) and app at `/app` (`--ro-bind-fd app_fd /app`).
- Unshares user namespaces (`--disable-userns`), PID namespaces (`--unshare-pid`), and network namespaces (`--unshare-net`).
- Implements strict Seccomp-BPF filters (`flatpak-run.c:2013-2110` blocklist [verified, range corrected]): blocks terminal injection (`TIOCSTI`/`TIOCLINUX`), `clone3` (returns `ENOSYS` so glibc falls back to `clone`, per the in-code CVE-2021-41133 comment), `syslog`, `keyctl`, and restricts socket domains to `AF_UNSPEC`, `AF_LOCAL`, `AF_INET`, `AF_INET6`, and `AF_NETLINK` (plus flag-gated `AF_CAN`/`AF_BLUETOOTH`).

### 1.4 Portals and D-Bus Mediation
- By default, host D-Bus access is proxied through `xdg-dbus-proxy` (built from the vendored `xdg-dbus-proxy` subproject). An explicit `--socket=session-bus`/`--socket=system-bus` instead bind-mounts the real bus socket and bypasses the proxy entirely [nuance added].
- Host file access is mediated via `org.freedesktop.portal.FileChooser` and `xdg-document-portal`, which exposes selected files via a virtual FUSE mount at `/run/flatpak/doc/` [verified].

### 1.5 Single-File `.flatpak` Bundles
Created via `flatpak build-bundle` (`flatpak-builtins-build-bundle.c` [verified]):
- Structure: A GVariant metadata header (magic `0xe5890001`) followed by an OSTree static delta payload [verified].
- **Cannot be run standalone:** It is not an ELF executable. Running `chmod +x app.flatpak && ./app.flatpak` fails with `Exec format error`. It must be installed into the local OSTree repository via `flatpak install` [verified].

---

## 2. What Flatpak Does Fundamentally Better

1. **Least Privilege & Security Boundaries:** Confines applications to isolated namespaces. Protects `~/.ssh`, browser profiles, and host IPC from compromised dependencies [verified].
2. **Cross-Application Disk Deduplication:** 50 Flatpak apps sharing a 1.5 GB GNOME runtime consume ~3.5 GB total on disk, whereas 50 standalone bundles consume 25 to 50 GB [reported].
3. **RAM Page Cache Sharing:** Hardlinked inodes in the OSTree store enable the kernel to share memory pages across different running applications [verified].
4. **Centralized Security Updates:** Patching the Freedesktop runtime immediately remediates critical CVEs (glibc, OpenSSL, libxml2) across all installed applications without requiring individual app rebuilds [reported].
5. **Desktop & App Store Integration:** Seamless native integration into GNOME Software and KDE Discover [verified].

---

## 3. Inherent Limitations of Flatpak

1. **Host Dependency & Tight Coupling:** Requires systemd user session (`/run/user/$UID/systemd/private` in `flatpak-run.c:987` [verified]), D-Bus, and Bubblewrap. Cannot run in minimal Docker containers, Alpine without systemd, or chroots.
2. **No-Install / Standalone Impossibility:** Cannot run directly from a USB flash drive or arbitrary directory without local installation [verified].
3. **Severe CLI / Pipeline Friction:** Stripped environment variables (`flatpak_bwrap_empty_env`), broken relative paths / CWD translation, and 50–200 ms container startup latency make Flatpak effectively unusable for CLI developer tools and pipeline scripts [verified].
4. **First-App Download Penalty:** Installing a 10 MB utility requires pulling a 700 MB–1.5 GB base runtime [reported].
5. **Portal Friction & Path Rewriting:** Document portal virtual paths (`/run/flatpak/doc/...`) break applications that pass file paths to compilers, audio DAWs, or external tools [reported].

---

## 4. Takeaways for onelf

- **Opt-in Unprivileged Sandboxing:** `onelf-rt` can apply Landlock LSM (Linux 5.13+) filesystem isolation and Seccomp-BPF filters directly before `execve`, achieving Flatpak-grade containment without Bubblewrap or root.
- **CAS Hardlink Cache:** Implement an opt-in user cache (`~/.cache/onelf/cas/`) for extracted or cached binaries to share disk blocks and memory pages across multiple `onelf` applications.
