// SPDX-License-Identifier: GPL-2.0-or-later
// tlg: the game's Lua loadbuffer (HavokScript) is redirected here (src/probe.c,
// install_lua_hook). utils.lua gets a tick that loads "--TLGSET" every 15 frames; that chunk
// is replaced by code applying the Effects settings to the game's post-process objects, so
// menu changes apply live. "--TLGLOG <text>" chunks print <text> (data out of Lua).
#include "tlg_settings.h"
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <string_view>

namespace {
using LoadFn = int(__attribute__((sysv_abi))*)(void*, void*, const char*, uint64_t,
                                                const char*);
LoadFn original;

constexpr std::string_view Bootstrap = R"(
do local n,ls=0,loadstring or load RegisterTick(function() n=n+1 if n>=15 then n=0
local f,e=ls('--TLGSET') local ok=true if f then ok,e=pcall(f) end
if (not f or not ok) and e~=_TLGERR then _TLGERR=e local g=ls('--TLGLOG error: '..tostring(e)) if g then g() end end
end end) end
)";

// Shared by every TLGSET chunk: Scale keeps the game's own value per object property and
// writes it times pct/100, or plus add when given (vectors: the listed components). A value differing from our last
// write was set by the game (cutscene, area change): it becomes the new base. Feature turns a
// pass off at 0% (it costs nothing then) and back on when the game had it.
constexpr std::string_view Prelude = R"(
local ls=loadstring or load
local function L(s) local f=ls('--TLGLOG '..s) if f then f() end end
_TLGB=_TLGB or {}
local B=_TLGB
local function Parts(v) local t={} for n in tostring(v):gmatch('%S+') do t[#t+1]=tonumber(n) or 0 end return t end
local function Scale(o,key,prop,pct,parts,add)
  if not o then return end
  local cur=o[prop]
  local s=tostring(cur)
  local e=B[key]
  if not e or s~=e.w then e={b=parts and Parts(cur) or cur} B[key]=e end
  if parts then
    if type(cur)~='userdata' then return end
    local t={} for i=1,4 do t[i]=e.b[i] or 0 end
    for _,i in ipairs(parts) do t[i]=add and t[i]+add or t[i]*pct/100 end
    local n=Vector(t[1],t[2],t[3],t[4])
    if tostring(n)~=s then o[prop]=n end
  else
    if type(cur)~='number' then return end
    local w=add and e.b+add or e.b*pct/100
    if w~=cur then o[prop]=w end
  end
  e.w=tostring(o[prop])
end
B.off=B.off or {}
local function Feature(o,name,pct)
  if not o or type(o.features)~='string' then return end
  local on=o.features:find(name,1,true)~=nil
  if pct==0 and on then o.features='~'..name B.off[name]=true
  elseif pct>0 and B.off[name] then B.off[name]=nil if not on then o.features='|'..name end end
end
local pp=FindObject('_default_env_pp')
local cam=FindObject('_trico_camera')
local cs=FindObject('_default_env_cs')
local sk=FindObject('_default_env_sk')
local XY,XZ,ALL,XYZ={1,2},{1,3},{1,2,3,4},{1,2,3}
)";

// Development: the file named by TLG_LUA_EXEC runs once each time it changes (live console).
std::string DevChunk() {
    static const char* path = std::getenv("TLG_LUA_EXEC");
    static std::filesystem::file_time_type seen{};
    std::error_code error;
    if (!path) return {};
    const auto time = std::filesystem::last_write_time(path, error);
    if (error || time == seen) return {};
    seen = time;
    std::ifstream file(path);
    std::stringstream text;
    text << file.rdbuf();
    std::printf("Lua: running %s\n", path);
    return "\ndo\n" + text.str() + "\nend\n";
}

// Wider than 16:9 the resolution patch widens the UI canvas to 1080*W/H (tlg_patches.py); the
// subtitle layout still centers on 1920, so shift it right by half the extra width.
int SubtitleShift() {
    const char* resolution = std::getenv("TLG_RESOLUTION_PATCH");
    int width = 0, height = 0;
    if (!resolution || std::sscanf(resolution, "%dx%d", &width, &height) != 2 || height <= 0 ||
        width * 9 <= height * 16)
        return 0;
    const int ui_width = static_cast<int>(1080.0 * width / height + 0.5);
    return (ui_width - 1920) / 2;
}

std::string SetChunk() {
    static const int subtitle_shift = SubtitleShift();
    const auto& s = TlgSettings::Get();
    std::string code(Prelude);
    char line[1024];
    std::snprintf(line, sizeof(line),
                  "Scale(pp,'bloom','bloomAmount',%d) Feature(pp,'Bloom',%d)\n"
                  "Scale(pp,'ao','saoIntensity',%d,XY) Feature(pp,'SSAO',%d)\n"
                  "Scale(pp,'ssr','ssrStrength',%d) Feature(pp,'SSR',%d)\n"
                  "Scale(pp,'blur','cameraBlurScale',%d) Feature(pp,'CameraBlur',%d)\n"
                  "Scale(pp,'ca','chromaticAberrationAmount',100,nil,%.4f)\n"
                  "Scale(pp,'vig','vignetteParams',100,XZ,%.4f)\n"
                  "Scale(pp,'sharp','sharpenScale',%d)\n"
                  "Scale(sk,'lod','viewDistanceScale',%d,XYZ)\n",
                  s.bloom.load(), s.bloom.load(), s.ssao.load(), s.ssao.load(), s.ssr.load(),
                  s.ssr.load(), s.motion_blur.load(), s.motion_blur.load(),
                  s.chromatic.load() * 0.002, s.vignette.load() * 0.01, s.game_sharpen.load(),
                  s.lod.load());
    code += line;
    if (subtitle_shift) {
        // Re-applied every tick: SubtitleSystem:Initialize resets it to (0, -OFFSET_Y).
        std::snprintf(line, sizeof(line),
                      "if Subtitle_SetParam then Subtitle_SetParam(%d,-(SubtitleSystem and "
                      "SubtitleSystem.OFFSET_Y or 64)) end\n",
                      subtitle_shift);
        code += line;
    }
    code += DevChunk();
    return code;
}

bool StartsWith(const char* buffer, uint64_t size, std::string_view prefix) {
    return size >= prefix.size() && std::memcmp(buffer, prefix.data(), prefix.size()) == 0;
}

// Development: every chunk the game loads is written to the folder named by TLG_LUA_DUMP.
void Dump(const char* buffer, uint64_t size, const char* name) {
    static const char* dir = std::getenv("TLG_LUA_DUMP");
    static int count = 0;
    if (!dir) return;
    std::string file = name ? name : "chunk";
    for (char& c : file)
        if (c == '/' || c == '\\' || c == ':' || c == '@' || c == '=') c = '_';
    std::filesystem::create_directories(dir);
    std::ofstream(std::string(dir) + "/" + std::to_string(count++) + "_" + file, std::ios::binary)
        .write(buffer, static_cast<std::streamsize>(size));
}
} // namespace

extern "C" void tlg_lua_status(uintptr_t loadbuffer) {
    original = reinterpret_cast<LoadFn>(loadbuffer);
}

extern "C" __attribute__((sysv_abi)) int tlg_lua_load(void* L, void* options, const char* buffer,
                                                      uint64_t size, const char* name) {
    static constexpr std::string_view Empty = "--";
    if (StartsWith(buffer, size, "--TLGLOG ")) {
        std::printf("Lua: %.*s\n", static_cast<int>(size - 9), buffer + 9);
        std::fflush(stdout);
        return original(L, options, Empty.data(), Empty.size(), name);
    }
    if (StartsWith(buffer, size, "--TLGSET")) {
        static std::string code; // game thread only
        code = SetChunk();
        return original(L, options, code.data(), code.size(), name);
    }
    Dump(buffer, size, name);
    static constexpr std::string_view Marker = "function RegisterTick(";
    if (std::string_view(buffer, size).find(Marker) != std::string_view::npos) {
        std::string patched(buffer, size);
        patched += Bootstrap;
        std::printf("Lua: settings tick added to %s\n", name ? name : "?");
        std::fflush(stdout);
        return original(L, options, patched.data(), patched.size(), name);
    }
    return original(L, options, buffer, size, name);
}
