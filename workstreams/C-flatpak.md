# Deep-Dive Technical Research: Flatpak vs. Single-File Bundles (onelf)

**Target Ecosystem:** Flatpak (https://github.com/flatpak/flatpak, https://github.com/flatpak/flatpak-builder)  
**Evidence Standard:** [verified] (source code inspection), [reported] (issues/benchmarks/docs), [inferred] (architectural deduction).
**Fact-check (third pass, 2026-10-19):** citations and claims re-verified against flatpak main `ed564f7`, xdg-dbus-proxy `0.1.9` (`72b40c8`), bubblewrap `v0.12.0` (`2a76602`, the version pinned in `subprojects/bubblewrap.wrap`), and the Flathub summary API for runtime sizes.

---

## 1. Flatpak Architecture Overview

### 1.1 OSTree Storage Model
Flatpak is built on **OSTree** operating in `OSTREE_REPO_MODE_BARE_USER_ONLY` (`flatpak/common/flatpak-dir.c:5023` [verified]; the adjacent comment exempts old installations that still use `bare-user`). 
- When an application or runtime is installed, files are checked out as **POSIX hard links** pointing directly into the content-addressed object store (deploy checkout at `flatpak-dir.c:10134-10168`; appstream checkout block at `flatpak-dir.c:5689-5694`, same pattern) [verified at flatpak main `ed564f7`].
- Applications sharing identical files (e.g. standard runtime libraries, icons, fonts) consume zero additional disk space.
- The Linux kernel page cache indexes memory pages by `(device, inode)`. Because files are hardlinked to identical inodes on disk, multiple running Flatpak applications share physical RAM pages for identical libraries [verified; kernel mechanism re-demonstrated on the checking machine: two hard links to one inode, faulting all pages in through one name leaves every page resident under the other (mincore 0 -> 8192/8192 for a 32 MiB file; re-confirmed with an mmap fault path, since on ZFS plain read() populates the ARC, not the page cache)].

### 1.2 Runtimes & Extensions
- Applications build against standardized runtimes (`org.freedesktop.Platform`, `org.gnome.Platform`, `org.kde.Platform`).
- Runtime branches have bounded support windows before EOL, and they are not uniform: Freedesktop branches get a 2-year support period; GNOME branches are usually supported about a year and EOL'd at the next stable release (Flathub and flatpak runtime docs) [reported]. Flathub marks applications on EOL runtimes as deprecated, and `flatpak update` surfaces end-of-life warnings [reported].
- Hardware-specific drivers are mounted dynamically via extension points (e.g. `flatpak_get_gl_drivers`, `flatpak-utils.c:517`, matches `/sys/module/nvidia/version` with dots stripped to dashes into `org.freedesktop.Platform.GL.nvidia-<ver>`; the extension binds under `/usr/<directory>` from the extension's declared directory, `/usr/lib/x86_64-linux-gnu/GL` for the freedesktop GL extension, via `flatpak_run_add_extension_args`, `flatpak-run.c:128`) [verified in flatpak; the `directory: %{lib}/GL` value comes from freedesktop-sdk `elements/flatpak-images/platform.bst`, with `lib: "lib/%{gcc_triplet}"` in `include/install-dirs.yml`, not from the flatpak repo]. The driver list is `nvidia-<ver>`, `default`, `host`, and the `FLATPAK_GL_DRIVERS` environment variable (colon-separated) replaces it (`flatpak-utils.c:517-560`); an extension whose `enable-if` metadata key (`flatpak-dir-utils.c:500`, `:536`) contains `active-gl-driver` is selected when its last name component equals an entry in that list (`flatpak_extension_matches_reason`, `flatpak-utils.c:1666-1673`).

### 1.3 Bubblewrap (`bwrap`) Sandboxing & Seccomp
Flatpak constructs an isolated container using Bubblewrap (`flatpak-run.c:3656` [verified]):
- Mounts runtime at `/usr` (`--ro-bind-fd runtime_fd /usr`) and app at `/app` (`--ro-bind-fd app_fd /app`).
- Unshares user namespaces (`--unshare-user` + `--disable-userns`, `flatpak-run.c:2395-2396`; added only when bwrap is not setuid and the sandbox is new, otherwise `--assert-userns-disabled` or nothing, `flatpak-run.c:2382-2397`), PID namespaces (`--unshare-pid`, `flatpak-run.c:2429`, skipped when `FLATPAK_RUN_FLAG_PARENT_SHARE_PIDS` is set), and network namespaces (`--unshare-net`, `flatpak-run.c:410`, applied only when the app metadata does not grant `shared=network`) [verified].
- Implements strict Seccomp-BPF filters (`flatpak-run.c:2013-2110` blocklist [verified, range corrected]): blocks terminal injection (`TIOCSTI`/`TIOCLINUX`), `clone3` (returns `ENOSYS` so glibc falls back to `clone`, per the in-code CVE-2021-41133 comment), `syslog`, `keyctl`, and restricts socket domains to `AF_UNSPEC`, `AF_LOCAL`, `AF_INET`, `AF_INET6`, and `AF_NETLINK` (plus flag-gated `AF_CAN`/`AF_BLUETOOTH`).

### 1.4 Portals and D-Bus Mediation
- By default, host D-Bus access is proxied through `xdg-dbus-proxy` (built from the `xdg-dbus-proxy` subproject, a wrap-git pin to 0.1.9 / `72b40c8` in `subprojects/dbus-proxy.wrap`). An explicit `--socket=session-bus`/`--socket=system-bus` instead bind-mounts the real bus socket and bypasses the proxy entirely [nuance added].
- Host file access is mediated via `org.freedesktop.portal.FileChooser` and `xdg-document-portal`, which exposes selected files via a virtual FUSE mount (`document-portal/document-portal-fuse.c` in `flatpak/xdg-desktop-portal`); inside the sandbox flatpak bind-mounts the host's `<doc mount>/by-app/<app-id>` at `/run/flatpak/doc` (`flatpak-run.c:73`, `1913-1919`) [verified]. Portals matter for apps that lack a direct `--filesystem` grant.

### 1.5 Single-File `.flatpak` Bundles
Created via `flatpak build-bundle` (`flatpak-builtins-build-bundle.c` [verified]):
- Structure: A GVariant metadata header (magic `0xe5890001`, written at `flatpak-builtins-build-bundle.c:252`) followed by an OSTree static delta payload [verified].
- **Cannot be run standalone:** It is not an ELF executable. Running `chmod +x app.flatpak && ./app.flatpak` fails with `Exec format error`. It must be installed into the local OSTree repository via `flatpak install` [verified].

---

## 2. What Flatpak Does Fundamentally Better

1. **Least Privilege & Security Boundaries:** Confines applications to isolated namespaces. Protects `~/.ssh`, browser profiles, and host IPC from compromised dependencies, for apps that are not granted `--filesystem=home`/`host` or `--socket=session-bus` (many apps are) [inferred from the bwrap argument construction in `flatpak-run.c`; no isolation test was run].
2. **Cross-Application Disk Deduplication:** N Flatpak apps sharing one runtime store that runtime once, whereas N standalone bundles each carry their own copy of whatever libraries they bundle. Measured sizes (Flathub summary API, 2026-10-19): `org.gnome.Platform` 50 is 1.09 GB installed / 0.42 GB download, `org.freedesktop.Platform` 26.08 is 0.72 GB installed / 0.28 GB download. The earlier "1.5 GB runtime, ~3.5 GB for 50 apps, 25 to 50 GB for 50 bundles" figures have no source and are removed [estimate withdrawn]. A standalone bundle also carries only the libraries its app needs, not a whole runtime, so the per-bundle overhead is below the runtime size [inferred].
3. **RAM Page Cache Sharing:** Hardlinked inodes in the OSTree store enable the kernel to share memory pages across different running applications [verified].
4. **Centralized Security Updates:** Updating the Freedesktop runtime remediates CVEs in the libraries the apps take from it (glibc, OpenSSL, libxml2) for all installed applications without individual app rebuilds; running apps pick it up on their next start, and libraries an app bundles itself are not covered [reported/inferred].
5. **Desktop & App Store Integration:** Seamless native integration into GNOME Software and KDE Discover [reported].

---

## 3. Inherent Limitations of Flatpak

1. **Host Dependency & Tight Coupling:** Requires a `bwrap` binary (`flatpak_get_bwrap`, `flatpak-utils.c:652`). A setuid bwrap is supported: `flatpak_bwrap_is_unprivileged` (`flatpak-utils.c:662`, bwrap present and not setuid) only gates `--unshare-user`/`--disable-userns` (`flatpak-run.c:2366-2397`; the comment at `2379` says a setuid bwrap makes the seccomp filter security-critical) and a portal code path (`flatpak-portal.c:3118`). Unprivileged user-namespace support in the kernel is needed only when bwrap is not setuid. A systemd user session is not strictly required: the transient-unit cgroup tracking that opens `/run/user/$UID/systemd/private` (`flatpak-run.c:987`) fails soft, and its caller continues: "We still run along even if we don't get a cgroup, as nothing really depends on it" (comment wraps across `flatpak-run.c:641-642`, caller at `638-645`) [verified]. D-Bus is needed for portals and bus proxies; with no session bus the app still runs, just without bus access [inferred]. Minimal containers that block `clone(CLONE_NEWUSER)` (Docker's default seccomp profile does) or that ship no bwrap cannot run Flatpak apps, unless a setuid bwrap is present [reported/inferred].
2. **No-Install / Standalone Impossibility:** An app cannot be executed in place from a USB drive or arbitrary directory: it must be deployed into a Flatpak installation by the host's `flatpak`. The installation directory can be redirected (`FLATPAK_USER_DIR`, `flatpak-dir.c:2726`; `FLATPAK_SYSTEM_DIR`, `flatpak-dir.c:2000`), but the host still needs `flatpak` and `bwrap` [verified in source; no end-to-end run, flatpak is not installed on the checking machine].
3. **Severe CLI / Pipeline Friction:** The sandbox environment is the host environment minus a fixed unset blocklist (`LD_PRELOAD`, `LD_LIBRARY_PATH`, `TMPDIR`, `XDG_RUNTIME_DIR`, `PYTHONPATH`, ...; `default_exports` handling at `flatpak-run.c:664-746`), with a full strip only under `flatpak run --clear-env` (`--clearenv` added by `flatpak_run_apply_env_clear`, `flatpak-run.c:849`, on `FLATPAK_RUN_FLAG_CLEAR_ENV` set at `flatpak-builtins-run.c:414`; the option is `--clear-env`, `flatpak-builtins-run.c:186`). There is no CWD translation: flatpak passes `--chdir` only for an explicit `--cwd` (`flatpak-run.c:3930-3931`) and binds nothing for the caller's working directory. bwrap itself keeps the caller's cwd when that path exists inside the sandbox (for example under a granted `--filesystem`), otherwise it falls back to `$HOME`, then `/` (bubblewrap `bubblewrap.c:3447-3466`). So relative paths work when the cwd is visible in the sandbox and break otherwise [verified]. The commonly cited 50-200 ms container startup latency is [estimate, never measured]; the CLI-tool friction verdict itself stands [reported].
4. **First-App Download Penalty:** Installing a small utility on a machine without its runtime requires pulling the runtime: recent branches are 0.26-0.42 GB download and 0.67-1.09 GB installed (Flathub summary API, 2026-10-19: freedesktop 24.08/25.08/26.08, GNOME 47-50) [measured from the API; the figures are sizes of the published runtime, not a timed install].
5. **Portal Friction & Path Rewriting:** Document portal virtual paths (`/run/flatpak/doc/...`) break applications that pass file paths to compilers, audio DAWs, or external tools [reported].

---

## 4. Takeaways for onelf

- **Opt-in Unprivileged Sandboxing:** `onelf-rt` could apply Landlock LSM (Linux 5.13+ for filesystem rules, kernel docs; TCP network rules need Landlock ABI v4) and Seccomp-BPF filters directly before `execve`, without Bubblewrap or root. onelf has no Landlock or seccomp code today (`git grep -i landlock` and `seccomp` over HEAD `7438f5a` find nothing). This is weaker than Flatpak's containment: Landlock denies access but does not hide paths or give the app a private mount view, and it adds no PID/IPC namespace or D-Bus mediation [inferred from the Landlock docs and the bwrap arguments above].
- **CAS Hardlink Cache:** `onelf-rt` already has an opt-in cache mode (`ONELF_MODE=cache`; last rung of the fallback ladder) that stores files by BLAKE3 hash and mode under `<cache root>/cas/` (default `~/.cache/onelf/`) and hardlinks them into per-package trees (`crates/onelf-rt/src/cache.rs:167`, `:284`, `:338`; `cache_layout::resolve_root`). Because the blob is one inode shared across packages, the disk and page-cache sharing mechanism of section 1.1 applies to that mode [inferred; not run]. The gap versus Flatpak is that the default modes (memfd, FUSE, tmpfs, rundir) do not use it.
