#!/usr/bin/env bash
# Builds tlg_dlss.dll (gpu/dlss_bridge, the only code that uses the NVIDIA DLSS SDK) with
# MSVC and puts it with NVIDIA's nvngx_dlss.dll next to out/tlg-probe.exe; package.sh ships both.
# Needs Visual Studio 2022 (Build Tools) and a checkout of https://github.com/NVIDIA/DLSS:
#   DLSS_SDK_ROOT=F:/sdk/DLSS bash packaging/windows/build_dlss.sh
set -euo pipefail
cd -- "$(dirname -- "$0")/../.."
sdk=${DLSS_SDK_ROOT:?Set DLSS_SDK_ROOT to a checkout of github.com/NVIDIA/DLSS}
cmake=${CMAKE_EXE:-cmake}
# The newest Visual Studio found by vswhere (GitHub's windows runners move to new versions);
# DLSS_VS_GENERATOR overrides.
generator=${DLSS_VS_GENERATOR:-}
if [[ -z $generator ]]; then
    vswhere="/c/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe"
    major=$("$vswhere" -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 \
        -property installationVersion 2>/dev/null | tr -d '\r' | cut -d. -f1)
    case $major in
        18) generator="Visual Studio 18 2026" ;;
        *)  generator="Visual Studio 17 2022" ;;
    esac
fi
# Only the Vulkan headers: MSYS2's C headers must not reach MSVC.
rm -rf out/vkinclude && mkdir -p out/vkinclude
cp -r /clang64/include/vulkan /clang64/include/vk_video out/vkinclude/
"$cmake" -S gpu/dlss_bridge -B out/dlss-bridge -G "$generator" -A x64 \
    -DDLSS_SDK_ROOT="$(cygpath -m "$sdk")" -DVULKAN_INCLUDE="$(cygpath -m "$PWD/out/vkinclude")"
"$cmake" --build out/dlss-bridge --config Release
cp out/dlss-bridge/Release/tlg_dlss.dll "$sdk/lib/Windows_x86_64/rel/nvngx_dlss.dll" out/
cp "$sdk/LICENSE.txt" out/NVIDIA-DLSS-LICENSE.txt
echo "DLSS bridge ready: out/tlg_dlss.dll, out/nvngx_dlss.dll"
