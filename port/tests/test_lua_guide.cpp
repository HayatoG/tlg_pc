// The button hints edit (tlg_lua.cpp): with hide_button_hints the game stops drawing the Guide
// system's hint boxes (the frame with the button to press). The setting comes from tlg.ini or
// TLG_HIDE_BUTTON_HINTS.
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include "tlg_settings.h"

#ifndef _WIN32
static int _putenv_s(const char* name, const char* value) { return setenv(name, value, 1); }
#endif

extern "C" void tlg_lua_status(uintptr_t loadbuffer);
extern "C" __attribute__((sysv_abi)) int tlg_lua_load(void* L, void* options, const char* buffer,
                                                      uint64_t size, const char* name);

namespace {

std::string loaded;  // the chunk the game would have loaded

int FakeLoad(void*, void*, const char* buffer, uint64_t size, const char*) {
    loaded.assign(buffer, size);
    return 0;
}

// The part of game/scripts/guide/guidesystem.lua the edit looks for.
const char* GuideSystemChunk =
    "GuideSystem = {\n"
    "\tCreateObject = function(self)\n"
    "--\t\tif true then return end\t--\tguide system off\n"
    "\t\tif self.isCreateObj then\n"
    "\t\t\tGuide_SetGuideNum( self.ObjectNum, self.group_size, self.BaseObjectNum )\n"
    "\t\t\tGuide_CreateGuide( 'GuideSet_Basic_Jump', 1 )\n"
    "\t\tend\n"
    "\tend,\n"
    "}\n";

// The part of game/scripts/stages/common/guide/basic_system.lua the edit looks for.
const char* BasicSystemChunk =
    "function Guide_Basic_Reset()\n"
    "\tGuideSystem:SetSysSaveLoadFlg(true)\n"
    "\tGuideSystem:Start()\n"
    "end\n";

// The same call inside a comment, the way game/scripts/common/gamesetuptbl.lua explains it:
// an anchor inside a comment is not the code and must not be edited.
const char* CommentedChunk =
    "function RestartStage_4th(area)\n"
    "--\t\t\tGuideSystem:Reset()\t--\tGuide_Basic_Reset->GuideSystem:Start() is called there\n"
    "end\n";

std::string Load(const char* chunk, const char* name) {
    loaded.clear();
    tlg_lua_load(nullptr, nullptr, chunk, std::strlen(chunk), name);
    return loaded;
}

}  // namespace

int main() {
    tlg_lua_status(reinterpret_cast<uintptr_t>(&FakeLoad));
    auto& v = TlgSettings::Get();

    // Off: every chunk reaches the game untouched.
    v.hide_button_hints = false;
    assert(Load(GuideSystemChunk, "data_trico/game/scripts/guide/GuideSystem.lua") == GuideSystemChunk);
    assert(Load(BasicSystemChunk, "data_trico/game/scripts/stages/common/guide/Basic_System.lua") ==
           BasicSystemChunk);
    assert(Load(CommentedChunk, "data_trico/game/scripts/common/GameSetupTbl.lua") == CommentedChunk);

    // On: the guide system creates no guide object (nothing to draw) and the engine's guide
    // system is turned off (the game's own switch, the one the E3 build path uses).
    v.hide_button_hints = true;
    const std::string guide = Load(GuideSystemChunk, "data_trico/game/scripts/guide/GuideSystem.lua");
    assert(guide.find("if true then return end\t-- tlg: the button hints stay hidden") != std::string::npos);
    assert(guide.find("Guide_SetGuideNum") != std::string::npos);  // the rest of the file stays
    assert(guide.find("CreateObject = function(self)\n\t\tif true then return end") != std::string::npos);
    const std::string basic = Load(BasicSystemChunk, "data_trico/game/scripts/stages/common/guide/Basic_System.lua");
    assert(basic.find("GameConfig.guideSystem = 0") != std::string::npos);
    assert(basic.find("\tGuideSystem:Start()\n") != std::string::npos);  // still called, still in place

    // A chunk without the anchors is left alone: another game build keeps its own scripts.
    const char* other = "function Something()\n\tGuideSystem:Start()\nend\n";
    assert(Load(other, "data_trico/game/scripts/other.lua") == other);
    // A call inside a comment is left alone too.
    assert(Load(CommentedChunk, "data_trico/game/scripts/common/GameSetupTbl.lua") == CommentedChunk);

    // tlg.ini and the environment carry the option.
    const char* path = "lua-guide-test.ini";
    {
        std::ofstream out(path);
        out << "hide_button_hints=1\n";
    }
    _putenv_s("TLG_CONFIG", path);
    _putenv_s("TLG_HIDE_BUTTON_HINTS", "");
    TlgSettings::Load();
    assert(v.hide_button_hints);
    _putenv_s("TLG_HIDE_BUTTON_HINTS", "0");
    TlgSettings::Load();
    assert(!v.hide_button_hints);

    // Save keeps it in the file (the in-game menu writes the same keys).
    v.hide_button_hints = true;
    TlgSettings::Save();
    {
        std::ifstream in(path);
        std::stringstream text;
        text << in.rdbuf();
        assert(text.str().find("hide_button_hints=1\n") != std::string::npos);
    }
    std::remove(path);
    std::printf("lua-guide-test ok\n");
    return 0;
}
