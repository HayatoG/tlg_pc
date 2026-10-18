#!/usr/bin/env bash
# Builds dist/tlg-linux-x86_64.tar.gz after `bash build.sh`: "The Last Guardian" (the launcher,
# frozen with PyInstaller so players need no Python or Tk), out/tlg-probe with libtlggpu.so, the
# libraries they need that a desktop may lack (out/lib: SDL3, FFmpeg, Zydis, fmt, ...), the
# preparation scripts and the player README. No game or console file may ship.
set -euo pipefail
cd -- "$(dirname -- "$0")/../.."
[[ -f out/tlg-probe && -f out/gpu/libtlggpu.so ]] || { echo 'Build first: bash build.sh' >&2; exit 1; }
name=${TLG_PACKAGE_NAME:-tlg-linux-x86_64}
python=${PYTHON:-python3}
if [[ ! -x out/pyenv/bin/python ]]; then
    "$python" -m venv out/pyenv
fi
out/pyenv/bin/python -m pip install -q --disable-pip-version-check pyinstaller iced-x86==1.21.0
# The scripts run inside the executable (--script): the standard modules they import come along,
# and iced-x86 for scripts/isa_rewrite.py (CPUs without MOVBE/BMI1/LZCNT/SSE4A).
hidden=()
for module in argparse base64 collections hashlib json re shutil struct tempfile xml.etree.ElementTree \
              urllib.request runpy iced_x86; do
    hidden+=(--hidden-import "$module")
done
out/pyenv/bin/python -m PyInstaller --noconfirm --clean --log-level WARN --windowed \
    --name "The Last Guardian" --distpath out/pyi-dist --workpath out/pyi-work --specpath out/pyi-work \
    --paths "$PWD/scripts" --paths "$PWD/launcher" "${hidden[@]}" launcher/tlg_launcher.py

dest=out/stage/$name
rm -rf -- out/stage
mkdir -p "$dest/out/gpu" "$dest/out/lib" "$dest/launcher" "$dest/system_lib"
cp -r "out/pyi-dist/The Last Guardian/." "$dest/"
cp launcher/tlg.png "$dest/launcher/"
cp -r launcher/assets "$dest/launcher/"
strip --strip-debug -o "$dest/out/tlg-probe" out/tlg-probe
strip --strip-debug -o "$dest/out/gpu/libtlggpu.so" out/gpu/libtlggpu.so
[[ -f out/tlg-gpu-capabilities ]] && strip -o "$dest/out/tlg-gpu-capabilities" out/tlg-gpu-capabilities
# Libraries to bundle: everything the two ELF files load except the base system (glibc, the C++
# runtime, the Vulkan loader and drivers, X11/Wayland, audio servers), which must come from the
# player's distribution to match its drivers.
system='^(ld-linux|libc|libm|libdl|libpthread|librt|libmvec|libresolv|libutil|libstdc\+\+|libgcc_s|libvulkan|libGL|libEGL|libGLX|libGLdispatch|libX|libxcb|libwayland|libdrm|libasound|libpulse|libpipewire|libudev|libdbus|libsystemd|libz\.|libgomp|libcap|libffi)'
ldd out/tlg-probe out/gpu/libtlggpu.so | awk '/=> \// {print $1, $3}' | sort -u | while read -r soname path; do
    [[ $soname == libtlggpu.so ]] && continue
    [[ $soname =~ $system ]] && continue
    cp -L "$path" "$dest/out/lib/$soname"
done
# SDL3 loads its video/audio backends at run time from the player's system: nothing else to copy.
cp -r scripts "$dest/"
find "$dest" -name __pycache__ -prune -exec rm -r {} +
cp LICENSE packaging/README-player.md "$dest/"
cp packaging/linux/install_desktop.sh "$dest/"
cat > "$dest/system_lib/LEIA-ME.txt" <<'TXT'
Coloque aqui o libSceNgs2.sprx do firmware do seu PS4 (/system/common/lib) para ter som.
Put libSceNgs2.sprx from your PS4 firmware (/system/common/lib) here for audio.
TXT
bash packaging/check_package.sh "$dest"
mkdir -p dist
tar -C out/stage -czf "dist/$name.tar.gz" "$name"
du -sh "$dest" "dist/$name.tar.gz"
