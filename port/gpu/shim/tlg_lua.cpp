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

// Debug menus (setting level_select): the GoldHEN "Level Select + QA Menu" patch by illusiony
// and DanielSvoboda, applied to the source. Startup gets the QA menu (in game: hold L1, press
// L3); the title menu's press-build level select is enabled (hold L1 as the menu closes).
// The game is paused while the QA menu is open. The menu also closes itself when a stage is
// picked, so its Hide resumes: paused, the new stage's fade-in (a game-time delay) never came.
constexpr std::string_view QaMenu = R"(
if not _TLGQA then _TLGQA=true
local function Registered(f) for _,v in ipairs(tick_funcs) do if v==f then return true end end return false end
RegisterTick(function()
  if MS.PadGetHold(PadButton.L1) and MS.PadGetDown(PadButton.L3) then
    if Registered(ControllerMenu.Tick) then
      if ControllerMenu.Hide then ControllerMenu.Hide() end
    else _TLGQA_UNLOAD=true DelayExec(function() RegisterTick(ControllerMenu.Tick) end) luaCommand("trico pause") end
  end
end)
Load("game/scripts/_editor/ControllerMenu")
local hide = ControllerMenu.Hide
ControllerMenu.Hide = function() hide() luaCommand("trico resume") end
end
)";

/// Edits game chunk `name` for the debug menus and the bridge fix; true when it changed.
bool GameEdits(std::string& patched, std::string_view name) {
    const auto& s = TlgSettings::Get();
    if (s.level_select && name == "data_trico/game/scripts/startup.lua") {
        patched += QaMenu;
        return true;
    }
    if (s.level_select && name == "data_trico/game/scripts/common/GameSetupTbl.lua") {
        // A stage started from the QA menu is loaded on top of the current one (StartStage
        // unloads nothing), so each switch held two stages and ran the GPU heap out of memory.
        // Do what the game's own restart does: disconnect the stage's regions, preload the new
        // ones, then unload what is still disconnected. The common regions stay.
        static constexpr std::string_view Blocker = "self.timeBlocker = CreateTimeBlocker()";
        static constexpr std::string_view Preloaded =
            "DelayExec( function() self:Start_Stage_2nd_PreloadWait(area) end )";
        const size_t blocker = patched.find(Blocker);
        const size_t preloaded = patched.find(Preloaded);
        if (blocker == std::string::npos || preloaded == std::string::npos || preloaded < blocker) {
            return false;
        }
        patched.insert(preloaded, "if _TLGQA_UNLOAD then _TLGQA_UNLOAD = nil RegionController.UnloadAll_IfDisconnect() end ");
        patched.insert(blocker + Blocker.size(),
                       " if _TLGQA_UNLOAD then for _, v in ipairs(Class('Region')) do"
                       " if OBJ[v].status ~= 'None' and not string.find(v, 'RG_common') then"
                       " RegionController.Disconnect(OBJ[v].regionName) end end"
                       " self:Disconnect_CommonRegion() end");
        return true;
    }
    if (s.level_select && name == "data_trico/game/scripts/stages/s01_Opening/missionScript.lua") {
        // Only the test guarding the L1 level select, not the press build's other changes.
        static constexpr std::string_view Test = "if gameConfig_buildId_Press==true then";
        static constexpr std::string_view Hold = "if MS.PadGetHold(PadButton.L1) then";
        for (size_t at = patched.find(Test); at != std::string::npos;
             at = patched.find(Test, at + 1)) {
            const size_t next = patched.find_first_not_of(" \t\r\n", at + Test.size());
            if (next != std::string::npos && patched.compare(next, Hold.size(), Hold) == 0) {
                patched.replace(at, Test.size(), "if true then");
                return true;
            }
        }
        return false;
    }
    // Bridge fix (setting bridge_fix): the GoldHEN "Collapsing Bridge Freeze Fix". The slow
    // motion while the bridge in the pit collapses can leave the game frozen; skip it.
    static constexpr std::string_view SlowMotion = "MS.SetGameSpeed(0.10, 0.2)";
    if (s.bridge_fix && name == "data_trico/game/scripts/stages/s10_Pit/missionScript.lua") {
        const size_t at = patched.find(SlowMotion);
        if (at == std::string::npos) {
            return false;
        }
        patched.insert(at, "--");
        return true;
    }
    return false;
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
    std::string patched(buffer, size);
    bool changed = false;
    if (patched.find(Marker) != std::string::npos) {
        patched += Bootstrap;
        std::printf("Lua: settings tick added to %s\n", name ? name : "?");
        changed = true;
    }
    if (name && GameEdits(patched, name)) {
        std::printf("Lua: edited %s\n", name);
        changed = true;
    }
    std::fflush(stdout);
    return changed ? original(L, options, patched.data(), patched.size(), name)
                   : original(L, options, buffer, size, name);
}
