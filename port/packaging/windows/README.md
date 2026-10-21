# tlg on Windows

The port builds and runs natively on 64-bit Windows 10 (1903+) / 11 with the same sources as
on Linux. Players: see `README-Windows.txt` (it ships in the package).

## Build

Install [MSYS2](https://www.msys2.org) (`winget install MSYS2.MSYS2`), open the
**MSYS2 CLANG64** shell and install the toolchain and libraries (the counterpart of
`shell.nix`):

```bash
pacman -S --needed git patch \
  mingw-w64-clang-x86_64-{toolchain,cmake,ninja,pkgconf,python} \
  mingw-w64-clang-x86_64-{vulkan-headers,vulkan-loader,vulkan-memory-allocator,glslang} \
  mingw-w64-clang-x86_64-{sdl3,fmt,boost,robin-map,xxhash,ffmpeg,zydis} \
  mingw-w64-clang-x86_64-{spirv-tools,spirv-headers,spirv-cross}
```

magic_enum, miniz and xbyak (not packaged by MSYS2) are submodules under `gpu/third_party/`.
Then, in the repository:

```bash
git submodule update --init --recursive
bash build.sh                      # out/tlg-probe.exe, out/tlg-gpu-capabilities.exe
TLG_GAME_DIR=F:/path/to/CUSA01623 python run.py
python launcher/tlg_launcher_win.py
bash packaging/windows/package.sh  # dist/tlg-windows-x86_64.zip: The Last Guardian.exe + DLLs
```

`run.py` is the Windows `run.sh` (same variables; works from a plain Windows Python too).
The package freezes the launcher with PyInstaller (a private venv in `out/pyenv`, from a
python.org Python) into `The Last Guardian.exe`, which also runs `run.py` (`--run`), the
preparation scripts (`--script`) and the game without the window (`--play`): players need no Python.
`Play The Last Guardian.exe` (`packaging/windows/play.c`) is a small native program that runs
`The Last Guardian.exe --play` from its folder and waits for it, for players who want to start the
game directly with the saved settings.
`patches.py` applies the built-in patches only to the game build they were checked against
(CUSA01623 01.02, by eboot.bin sha256; `TLG_FORCE_PATCHES=1` overrides); other builds run unpatched.
From a source tree it adds `C:\msys64\clang64\bin` (or `$MSYS2_ROOT`) to `PATH` for the DLLs.
`bash tools/fetch_fsr4_assets.sh` works in the CLANG64 shell as on Linux.

DLAA (optional, NVIDIA RTX): `DLSS_SDK_ROOT=<checkout of github.com/NVIDIA/DLSS, tag v310.9.16>
bash packaging/windows/build_dlss.sh` builds `tlg_dlss.dll` (`gpu/dlss_bridge`, the only code that
uses the NVIDIA SDK, compiled with MSVC 2022 or 2026) and copies it with `nvngx_dlss.dll` and
`NVIDIA-DLSS-LICENSE.txt` next to `out/tlg-probe.exe`; `package.sh` ships all three when present
(`TLG_REQUIRE_DLSS=1` makes their absence an error, as in CI, which fetches the SDK itself). The
renderer loads the bridge at run time (`vk_dlss.cpp`). DLSS runs at native resolution (DLAA) on
the game's own motion vectors (sky pass), with a sub-pixel jitter on the scene draws, before the
first post pass. Without the DLLs, or on a GPU without DLSS, the menu greys the DLAA setting out
and the game keeps its own anti-aliasing. Settings: `dlaa` in `tlg.ini` (menu: Image ›
Anti-aliasing; F8 toggles in game), `TLG_DLAA=0`, `TLG_DLSS=0`.

The NVIDIA DLSS SDK is NVIDIA's proprietary software under its own license
(`NVIDIA-DLSS-LICENSE.txt`), not under this repository's license; only the NVIDIA binaries ship,
and the SDK sources are not part of this repository.

The launcher texts are written in English with the Russian beside them; the other languages
are in `launcher/tlg_lang.py` (one list per language in the order of `KEYS`; a missing or
empty text falls back to English). The icon (`launcher/tlg.ico`/`.png`) is drawn by
`packaging/windows/make_icon.py` and built into `God of War III.exe`, `tlg-probe.exe` (the game
window) and `tlg-gpu-capabilities.exe`.

## What is different from Linux

| Linux | Windows |
|---|---|
| `mov rax, fs:[0]` rewritten to `gs:[0]`, GS base set with `arch_prctl` | GS is the TEB and cannot move. The loader rewrites the displacement to `gs:[0x1480 + 8*slot]` (the TEB's `TlsSlots[slot]`, same 9-byte instruction) and each guest thread keeps its TCB in that TLS slot. The slot is claimed first thing in `main` (Vulkan drivers take many). |
| One memfd for direct + flexible memory, `mmap(MAP_FIXED)` views | A pagefile-backed section; the PS4 range 64 GiB–1 TiB is reserved as one placeholder and views replace placeholders (`VirtualAlloc2`/`MapViewOfFile3`, as in shadPS4). Partial unmaps split views and restore page protections (GPU tracking). |
| `-no-pie`, heap below 1 TiB | `--disable-high-entropy-va`: heaps and thread stacks stay low and out of the PS4 range. |
| SIGSEGV handler, `sigsetjmp` recovery | Vectored exception handler; `tlg_setjmp`/`tlg_longjmp` (`src/compat_win.c`) restore all Win64 callee-saved registers without SEH unwinding (guest frames have no unwind data; clang's `__builtin_longjmp` restores a wrong frame pointer on Win64). |
| Guest thread stacks from `runtime_low_map` | Windows allocates them, fully committed (`pthread_attr_setstacksize`): guest code has no stack probes and would skip the guard page. The main thread stack is 16 MiB committed. |
| glibc `nanosleep`, monotonic condition variables | High-resolution waitable timers (`compat_sleep_ns`; winpthreads' sleep rounds to 15.6 ms); semaphore deadlines use `CLOCK_REALTIME` (winpthreads rejects monotonic condition variables). |
| `libtlggpu.so` | `libtlggpu.a`, linked into `tlg-probe.exe` by CMake (`gpu/CMakeLists.txt`), with a manifest for UTF-8 paths and long paths. |
| `execlp bash run.sh` (in-game restart) | `run.py` puts its command line in `TLG_RESTART_COMMAND`; the new launch waits for the old process (`--after PID`). The launcher keeps the game in a job object. |
| Mod overlay with symlinks | Symlinks when allowed (Developer Mode), else junctions for folders and hard links for files. |

Diagnostics added on the way: `TLG_FRAME_DUMP_TRIGGER=<file>` writes the guest display buffer
and the presented image of the next frame to `TLG_DUMP_DIR` (raw 32-bit pixels), which also
works for menus and movies.

Not ported: the watchdog/`--timeout` thread dumps (Linux signals), userfaultfd tracking
(`TLG_UFFD`), MangoHud, PGO (GCC flags) and
the `tests/` programs (several use Linux-only APIs).
