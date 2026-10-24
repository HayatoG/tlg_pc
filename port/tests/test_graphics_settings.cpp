// tlg.ini graphics keys (tlg_settings.cpp, tlg_graphics.h).
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include "tlg_graphics.h"
#include "tlg_settings.h"

#ifndef _WIN32
static int _putenv_s(const char* name, const char* value) { return setenv(name, value, 1); }
#endif

namespace G = TlgGraphics;

static std::string Read(const char* path) {
    std::ifstream in(path);
    std::stringstream s;
    s << in.rdbuf();
    return s.str();
}

int main() {
    assert(G::ParseDisplayMode("borderless") == G::Borderless && G::ParseDisplayMode("bogus") == G::Windowed);
    assert(G::ParseFpsLimit(240) == 240 && G::ParseFpsLimit(75) == 0);
    assert(G::ParseResolution("1440p") == 3 && G::ParseResolution("8K") == 0);
    assert(G::ParseEngineFps(240) == 240 && G::ParseEngineFps(90) == 120);
    assert(G::ParseFramesQueued(2) == 2 && G::ParseFramesQueued(0) == 0 && G::ParseFramesQueued(5) == 1);
    assert(G::ParseRcasStrength(100) == 100 && G::ParseRcasStrength(101) == 75 && G::ParseRcasStrength(-1) == 75);
    assert(G::RcasAttenuation(100) == 0.0f && G::RcasAttenuation(0) == 2.0f && G::RcasAttenuation(75) == 0.5f);
    assert(G::ParseRcasStrength(101, 50) == 50 && G::CasSharpness(100) == 1.0f && G::CasSharpness(-3) == 0.5f);
    assert(G::ClampColor(G::Gamma, 9.0f) == 2.0f && G::ClampColor(G::Contrast, 0.1f) == 0.5f);
    assert(G::ClampColor(G::Saturation, 0.0f / 0.0f) == 1.0f && G::ClampColor(G::Brightness, 0.25f) == 0.25f);
    assert(G::FsrPassRuns(true, false, 1280, 720, 2560, 1440) && !G::FsrPassRuns(false, false, 1280, 720, 2560, 1440));
    assert(G::FsrPassRuns(false, true, 1920, 1080, 1920, 1080) && !G::FsrPassRuns(true, false, 1920, 1080, 1920, 1080));
    assert(!G::FsrPassRuns(true, true, 2560, 1440, 1920, 1080));  // larger image: regular scaling
    assert(G::EffectiveFps(0, 120) == 120 && G::EffectiveFps(240, 120) == 120 && G::EffectiveFps(60, 240) == 60);
    // An unpatched engine steps 1/60 s per frame: presenting faster speeds the game up.
    assert(G::PresentLimit(120, 60) == 60 && G::PresentLimit(240, 120) == 120 && G::PresentLimit(240, 240) == 240);
    assert(G::PresentLimit(0, 60) == 0 && G::PresentLimit(30, 60) == 30);  // 0: paced by vblank

    const char* path = "graphics-settings-test.ini";
    {
        std::ofstream out(path);
        out << "display_mode=borderless\nvsync=0\nfps_limit=240\nasync_shaders=0\n"
               "render_resolution=1440p\nengine_fps=240\ndeferred_readback=0\nstale_readback=1\n"
               "fsr1=1\nrcas=0\nrcas_strength=40\nframes_queued=2\n"
               "smaa=1\ncas=1\ncas_strength=30\ncolor_adjust=1\ncolor_brightness=0.10\n"
               "color_contrast=1.20\ncolor_saturation=0.80\ncolor_gamma=9\n";
    }
    _putenv_s("TLG_CONFIG", path);
    _putenv_s("TLG_ASYNC_SHADERS", "");
    auto& v = TlgSettings::Get();
    // Filters on the final image are off by default.
    assert(!v.smaa && !v.cas && !v.color_adjust && v.cas_strength == 50 && v.color_gamma == 1.0f);
    TlgSettings::Load();
    assert(v.display_mode == G::Borderless && !v.vsync && v.fps_limit == 240 && !v.async_shaders);
    assert(v.render_resolution == 3 && v.engine_fps == 240 && !v.deferred_readback && v.stale_readback);
    assert(v.fsr1 && !v.rcas && v.rcas_strength == 40 && v.frames_queued == 2);
    assert(v.smaa && v.cas && v.cas_strength == 30 && v.color_adjust && v.color_gamma == 2.0f);
    assert(v.brightness == 0.10f && v.contrast == 1.20f && v.saturation == 0.80f);
    assert(!TlgSettings::GraphicsNeedRestart());
    assert(v.applied_engine_fps == 240);  // no TLG_ENGINE_FPS: the configured rate
    _putenv_s("TLG_ENGINE_FPS", "60");    // run.py: the frame rate patch did not apply
    TlgSettings::Load();
    assert(v.engine_fps == 240 && v.applied_engine_fps == 60 && !TlgSettings::GraphicsNeedRestart());
    _putenv_s("TLG_ENGINE_FPS", "");
    v.engine_fps = 120;
    assert(TlgSettings::GraphicsNeedRestart());
    v.fps_limit = 60;  // live: no restart because of it
    v.engine_fps = 240;
    assert(!TlgSettings::GraphicsNeedRestart());

    TlgSettings::Save();
    const std::string saved = Read(path);
    for (const char* line : {"display_mode=borderless\n", "vsync=0\n", "fps_limit=60\n", "async_shaders=0\n",
                             "render_resolution=1440p\n", "engine_fps=240\n", "deferred_readback=0\n",
                             "stale_readback=1\n", "fsr1=1\n", "rcas=0\n", "rcas_strength=40\n",
                             "frames_queued=2\n", "smaa=1\n", "cas=1\n", "cas_strength=30\n",
                             "color_adjust=1\n", "color_brightness=0.10\n", "color_contrast=1.20\n",
                             "color_saturation=0.80\n", "color_gamma=2.00\n"}) {
        assert(saved.find(line) != std::string::npos);
    }

    {
        std::ofstream out(path);
        out << "display_mode=huge\nfps_limit=7\nrender_resolution=8K\nengine_fps=1\n"
               "rcas_strength=250\nframes_queued=9\n";
    }
    _putenv_s("TLG_ASYNC_SHADERS", "1");  // the environment still wins at start
    v.async_shaders = false;
    TlgSettings::Load();
    assert(v.display_mode == G::Windowed && v.fps_limit == 0 && v.render_resolution == 0 && v.engine_fps == 120);
    assert(v.rcas_strength == 75 && v.frames_queued == 1);
    assert(v.async_shaders);
    std::remove(path);
    std::puts("PASS: graphics settings");
}
