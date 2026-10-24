// SPDX-License-Identifier: GPL-2.0-or-later
#include "tlg_overlay.h"

#include <algorithm>
#include <atomic>
#include <cfloat>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <mutex>
#include <vector>

#include <SDL3/SDL.h>
#include "tlg_settings.h"
#include "tlg_graphics.h"
#include "tlg_perf_stats.h"
extern "C" void runtime_restart(void); // src/probe.c: starts run.py again, ends this process
#include "common/elf_info.h"
#include "imgui.h"
#include "imgui_internal.h" // RegisterUserTexture (save pictures)
#include "imgui_impl_vulkan.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/vk_frame_capture.h"

// DejaVu Sans (Cyrillic), embedded (third_party/fonts, Bitstream Vera license).
#ifdef _WIN32
asm(".section .rdata,\"dr\"\n"
    ".balign 16\n"
    ".global tlg_font_ttf\n"
    "tlg_font_ttf:\n"
    ".incbin \"" TLG_FONT_PATH "\"\n"
    ".global tlg_font_ttf_end\n"
    "tlg_font_ttf_end:\n"
    ".text\n");
#else
asm(".section .rodata\n"
    ".balign 16\n"
    ".hidden tlg_font_ttf\n"
    ".global tlg_font_ttf\n"
    "tlg_font_ttf:\n"
    ".incbin \"" TLG_FONT_PATH "\"\n"
    ".hidden tlg_font_ttf_end\n"
    ".global tlg_font_ttf_end\n"
    "tlg_font_ttf_end:\n"
    ".previous\n");
#endif
extern "C" const unsigned char tlg_font_ttf[];
extern "C" const unsigned char tlg_font_ttf_end[];

namespace TlgOverlay {

namespace {

std::mutex imgui_mutex; // the ImGui context: window thread (input) and present thread
bool initialized = false;
std::atomic<bool> menu_open{false};
bool r3_down = false, l2_down = false;
std::atomic<bool> loading{false};
std::atomic<u32> loading_done{0}, loading_total{0};
std::atomic<u32> background_done{0}, background_total{0};
bool dirty = false; // settings changed while open: saved on close
int requested_tab = -1; // switch on the next frame (L1/R1, Q/E, menu opened)
// The game's text dialog (SetTextEntry), guarded by imgui_mutex.
bool text_entry_active = false;
std::string text_entry_prompt, text_entry_text;
// The game's save dialogs (sceSaveDataDialog): the list, a message the player answers
// (overwrite?, no space...), the "Saving..." panel and the "Game saved" toast. The save's text
// comes from the game; every other word is the port's, in the menu language. Guarded by
// imgui_mutex; the game's thread polls the atomics.
using SaveClock = std::chrono::steady_clock;
std::atomic<bool> choice_active{false};  // the list
std::atomic<int> choice_result{-1};      // -1 open, -2 cancelled, else the chosen index
std::atomic<bool> message_active{false};
std::atomic<int> message_result{-1};     // -1 open, 1 yes/OK, 2 no/cancel
int save_kind = 1;                       // 1 save, 2 load, 3 delete
std::vector<SaveRow> save_rows;
int choice_index = 0, choice_first = 0;  // selected row, first row shown (the list scrolls)
int message_code = 0, message_buttons = 0, message_focus = 1; // focus: 0 no/cancel, 1 yes/OK
u64 message_value = 0;
std::string message_text;
bool message_has_entry = false;
SaveRow message_entry;
bool progress_on = false;
int progress_kind = 1, progress_percent = -1;
std::string progress_text;
SaveClock::time_point progress_since{}, progress_until{}; // until: a panel shown for a moment
SaveClock::time_point toast_since{}, toast_until{};
int toast_kind = 0;
// The mouse (display pixels) and the last frame's rectangles: the rows, the message's buttons.
ImVec2 save_mouse{-1.0f, -1.0f};
std::vector<ImRect> save_row_rects;
ImRect save_button_rects[2];
// Save pictures: decoded on the game's thread, made textures on the present thread (null =
// none). Closed dialogs' textures wait in choice_retired until the backend has destroyed them.
std::vector<TlgPng::Image> choice_pictures;
std::vector<ImTextureData*> choice_textures, choice_retired;
std::atomic<bool> choice_retiring{false};
float base_scale = 1.0f;

// Present rate for the FPS counter.
std::chrono::steady_clock::time_point last_present{};
float frame_ms_avg = 0.0f;

void SetOpen(bool value) {
    if (menu_open.exchange(value) == value) {
        return;
    }
    ImGui::GetIO().MouseDrawCursor = value;
    if (value) {
        requested_tab = TlgSettings::Get().menu_tab;
    }
    if (!value && dirty) {
        dirty = false;
        TlgSettings::Save();
    }
}

ImGuiKey KeyFromSdl(SDL_Keycode key) {
    switch (key) {
    case SDLK_TAB: return ImGuiKey_Tab;
    case SDLK_LEFT: return ImGuiKey_LeftArrow;
    case SDLK_RIGHT: return ImGuiKey_RightArrow;
    case SDLK_UP: return ImGuiKey_UpArrow;
    case SDLK_DOWN: return ImGuiKey_DownArrow;
    case SDLK_PAGEUP: return ImGuiKey_PageUp;
    case SDLK_PAGEDOWN: return ImGuiKey_PageDown;
    case SDLK_HOME: return ImGuiKey_Home;
    case SDLK_END: return ImGuiKey_End;
    case SDLK_DELETE: return ImGuiKey_Delete;
    case SDLK_BACKSPACE: return ImGuiKey_Backspace;
    case SDLK_SPACE: return ImGuiKey_Space;
    case SDLK_RETURN: return ImGuiKey_Enter;
    case SDLK_KP_ENTER: return ImGuiKey_KeypadEnter;
    case SDLK_ESCAPE: return ImGuiKey_Escape;
    case SDLK_Q: return ImGuiKey_Q;
    case SDLK_E: return ImGuiKey_E;
    case SDLK_LCTRL: return ImGuiKey_LeftCtrl;
    case SDLK_RCTRL: return ImGuiKey_RightCtrl;
    case SDLK_LSHIFT: return ImGuiKey_LeftShift;
    case SDLK_RSHIFT: return ImGuiKey_RightShift;
    case SDLK_LALT: return ImGuiKey_LeftAlt;
    case SDLK_RALT: return ImGuiKey_RightAlt;
    default: return ImGuiKey_None;
    }
}

ImGuiKey KeyFromGamepad(u8 button) {
    switch (button) {
    case SDL_GAMEPAD_BUTTON_SOUTH: return ImGuiKey_GamepadFaceDown;
    case SDL_GAMEPAD_BUTTON_EAST: return ImGuiKey_GamepadFaceRight;
    case SDL_GAMEPAD_BUTTON_WEST: return ImGuiKey_GamepadFaceLeft;
    case SDL_GAMEPAD_BUTTON_NORTH: return ImGuiKey_GamepadFaceUp;
    case SDL_GAMEPAD_BUTTON_DPAD_UP: return ImGuiKey_GamepadDpadUp;
    case SDL_GAMEPAD_BUTTON_DPAD_DOWN: return ImGuiKey_GamepadDpadDown;
    case SDL_GAMEPAD_BUTTON_DPAD_LEFT: return ImGuiKey_GamepadDpadLeft;
    case SDL_GAMEPAD_BUTTON_DPAD_RIGHT: return ImGuiKey_GamepadDpadRight;
    case SDL_GAMEPAD_BUTTON_LEFT_SHOULDER: return ImGuiKey_GamepadL1;
    case SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER: return ImGuiKey_GamepadR1;
    case SDL_GAMEPAD_BUTTON_START: return ImGuiKey_GamepadStart;
    case SDL_GAMEPAD_BUTTON_BACK: return ImGuiKey_GamepadBack;
    default: return ImGuiKey_None;
    }
}

float PixelDensity(SDL_WindowID id) {
    SDL_Window* window = SDL_GetWindowFromID(id);
    const float density = window ? SDL_GetWindowPixelDensity(window) : 1.0f;
    return density > 0.0f ? density : 1.0f;
}

// Marks the settings dirty when a widget changed them.
template <typename T>
void Store(std::atomic<T>& target, T value, bool changed) {
    if (changed) {
        target = value;
        dirty = true;
    }
}

void Checkbox(const char* label, std::atomic<bool>& value) {
    bool v = value;
    const bool changed = ImGui::Checkbox(label, &v);
    Store(value, v, changed);
}

// A combo over `count` labels storing an index or a value from `values`.
void Choice(const char* label, std::atomic<int>& target, const char* const* labels, const int* values,
            int count) {
    int current = 0;
    for (int i = 0; i < count; ++i) {
        if ((values ? values[i] : i) == target.load()) current = i;
    }
    if (ImGui::Combo(label, &current, labels, count)) {
        Store(target, values ? values[current] : current, true);
    }
}

// The note for the item under the mouse or the gamepad/keyboard focus, shown in the footer.
const char* footer_help = nullptr;

void Help(const char* text) {
    if (text && (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled) || ImGui::IsItemFocused())) {
        footer_help = text;
    }
}

// Two-column rows: the name on the left, the control on the right.
bool BeginRows(const char* id) {
    if (!ImGui::BeginTable(id, 2, ImGuiTableFlags_SizingStretchProp)) {
        return false;
    }
    ImGui::TableSetupColumn("name", ImGuiTableColumnFlags_WidthStretch, 0.52f);
    ImGui::TableSetupColumn("value", ImGuiTableColumnFlags_WidthStretch, 0.48f);
    return true;
}

void Row(const char* label) {
    ImGui::TableNextRow();
    ImGui::TableNextColumn();
    ImGui::AlignTextToFramePadding();
    ImGui::TextUnformatted(label);
    ImGui::TableNextColumn();
    ImGui::SetNextItemWidth(-FLT_MIN);
    ImGui::PushID(label);
}

void CheckRow(const char* label, std::atomic<bool>& value, const char* help = nullptr) {
    Row(label);
    Checkbox("##value", value);
    Help(help);
    ImGui::PopID();
}

void ChoiceRow(const char* label, std::atomic<int>& target, const char* const* labels, const int* values,
               int count, const char* help = nullptr) {
    Row(label);
    Choice("##value", target, labels, values, count);
    Help(help);
    ImGui::PopID();
}

void InfoRow(const char* label, const char* text) {
    Row(label);
    ImGui::TextDisabled("%s", text);
    ImGui::PopID();
}

void SliderRow(const char* label, std::atomic<int>& value, int lo, int hi, const char* format, const char* help) {
    Row(label);
    int v = value;
    if (ImGui::SliderInt("##value", &v, lo, hi, format, ImGuiSliderFlags_AlwaysClamp)) {
        Store(value, std::clamp(v, lo, hi), true);
    }
    Help(help);
    ImGui::PopID();
}

void FloatRow(const char* label, std::atomic<float>& value, float lo, float hi, const char* format, const char* help) {
    Row(label);
    float v = value;
    if (ImGui::SliderFloat("##value", &v, lo, hi, format, ImGuiSliderFlags_AlwaysClamp)) {
        Store(value, std::clamp(v, lo, hi), true);
    }
    Help(help);
    ImGui::PopID();
}

const char* TL(const char* en, const char* pt);

// A float slider over a color range, with a button back to its neutral value.
void FloatSliderRow(const char* label, std::atomic<float>& value, const TlgGraphics::ColorRange& range,
                    const char* help) {
    Row(label);
    const ImGuiStyle& style = ImGui::GetStyle();
    const char* reset = TL("Reset", "Padrão");
    ImGui::SetNextItemWidth(-(ImGui::CalcTextSize(reset).x + style.FramePadding.x * 2 + style.ItemSpacing.x));
    float v = value;
    if (ImGui::SliderFloat("##value", &v, range.min, range.max, "%.2f", ImGuiSliderFlags_AlwaysClamp)) {
        Store(value, TlgGraphics::ClampColor(range, v), true);
    }
    Help(help);
    ImGui::SameLine();
    if (ImGui::SmallButton(reset)) {
        Store(value, range.neutral, true);
    }
    Help(help);
    ImGui::PopID();
}

const char* UpscalerLabel(int upscaler) {
    switch (upscaler) {
    case TlgSettings::UpscalerFsr3: return "FSR 3.1";
    case TlgSettings::UpscalerFsr4: return "FSR 4";
    case TlgSettings::UpscalerFsr411: return "FSR 4.1.1";
    case TlgSettings::UpscalerTaa: return "TAA";
    case TlgSettings::UpscalerDlss: return "DLSS";
    default: return "";
    }
}


// tlg: menu language. TLG_UI_LANG=pt_BR or en_US; otherwise the system locale (LANG/LC_*):
// Portuguese when it starts with "pt", English otherwise.
bool UiPortuguese() {
    static const bool pt = [] {
        for (const char* name : {"TLG_UI_LANG", "LC_ALL", "LC_MESSAGES", "LANG"}) {
            if (const char* v = std::getenv(name); v && *v) return v[0] == 'p' && v[1] == 't';
        }
        return false;
    }();
    return pt;
}
const char* TL(const char* en, const char* pt) { return UiPortuguese() ? pt : en; }
const Vulkan::Instance* overlay_instance = nullptr; // for the overlay's measurements

// The performance overlay's text with the current settings (also the menu's preview).
std::string OverlayText() {
    namespace P = TlgPerfStats;
    const auto& s = TlgSettings::Get();
    const unsigned items = s.overlay_items;
    if ((items & (P::Gpu | P::Cpu | P::Ram | P::Vram)) && overlay_instance) {
        P::Start(*overlay_instance);
    }
    P::Sample sample = P::Latest();
    sample.fps = frame_ms_avg > 0.0f ? 1000.0f / frame_ms_avg : 0.0f;
    sample.frame_ms = frame_ms_avg;
    sample.upscaler = UpscalerLabel(s.upscaler);
    return P::Format(sample, items, s.overlay_layout == 0);
}

constexpr const char* Unsupported = "Unavailable: game version or code signature mismatch.";


void ImageTab() {
    namespace G = TlgGraphics;
    auto& s = TlgSettings::Get();
    ImGui::SeparatorText(TL("Display", "Tela"));
    if (BeginRows("##display")) {
        static const char* const modes[] = {TL("Windowed", "Janela"), TL("Borderless window", "Janela sem borda"), TL("Fullscreen", "Tela cheia")};
        ChoiceRow(TL("Display mode", "Modo de exibição"), s.display_mode, G::DisplayModeCount == 3 ? modes : G::DisplayModeNames.data(),
                  nullptr, G::DisplayModeCount, TL("Windowed, borderless window or exclusive fullscreen.", "Janela, janela sem borda ou tela cheia exclusiva."));
        CheckRow("VSync", s.vsync, TL("Waits for the monitor: no tearing, a little more input delay.", "Espera o monitor: sem tearing, um pouco mais de atraso de entrada."));
        ImGui::EndTable();
    }
    const int iw = s.image_width, ih = s.image_height, ww = s.window_width, wh = s.window_height;
    const bool upscaling = iw < ww && ih < wh;
    const bool downscaling = iw > ww || ih > wh;
    const bool rcas_blocked = s.rcas && !s.rcas_applied;
    // tlg: only spatial filters on the final image. The temporal upscalers (FSR 3/4, TAA, DLSS) were
    // built for GoW3's pipeline and make TLG's image shake, so they are not offered here.
    ImGui::SeparatorText(TL("Scaling and sharpening", "Escala e nitidez"));
    if (BeginRows("##scaling")) {
        CheckRow(TL("Upscale with FSR 1", "Ampliar com FSR 1"), s.fsr1,
                 TL("Enlarges the game image when it is smaller than the window (spatial filter, no shimmer).", "Amplia a imagem do jogo quando ela é menor que a janela (filtro espacial, sem tremor)."));
        // tlg: one sharpening filter at a time: FSR 1's RCAS or AMD CAS (stored as rcas / cas).
        static const char* const filters[] = {TL("Off", "Desligada"), "RCAS (FSR 1)", "CAS (AMD)"};
        int filter = s.cas ? 2 : s.rcas ? 1 : 0;
        Row(TL("Sharpening", "Nitidez"));
        if (ImGui::Combo("##value", &filter, filters, 3)) {
            Store(s.rcas, filter == 1, true);
            Store(s.cas, filter == 2, true);
        }
        Help(rcas_blocked && !s.cas && downscaling ? TL("No effect: the game's image is larger than the window.", "Sem efeito: a imagem do jogo é maior que a janela.")
             : rcas_blocked && !s.cas            ? TL("RCAS needs FSR 1 here: the game's image is smaller than the window. CAS works at any size.", "O RCAS precisa do FSR 1 aqui: a imagem do jogo é menor que a janela. O CAS funciona em qualquer tamanho.")
                                                 : TL("Sharpens the final image. RCAS comes with FSR 1; CAS (AMD Contrast Adaptive Sharpening) is softer on noise and works at any size.", "Deixa a imagem final mais nítida. O RCAS vem com o FSR 1; o CAS (AMD Contrast Adaptive Sharpening) realça menos o ruído e funciona em qualquer tamanho."));
        ImGui::PopID();
        if (s.cas) {
            SliderRow(TL("Sharpening strength", "Intensidade da nitidez"), s.cas_strength, 0, 100, "%d%%", TL("How strong the CAS sharpening is.", "Quão forte é a nitidez do CAS."));
        } else {
            ImGui::BeginDisabled(!s.rcas || rcas_blocked);
            SliderRow(TL("Sharpening strength", "Intensidade da nitidez"), s.rcas_strength, 0, 100, "%d%%", TL("How strong the sharpening is.", "Quão forte é a nitidez."));
            ImGui::EndDisabled();
        }
        ImGui::EndTable();
    }
    ImGui::SeparatorText(TL("Anti-aliasing", "Anti-aliasing"));
    if (BeginRows("##antialiasing")) {
        CheckRow("SMAA 1x", s.smaa,
                 TL("Smooths jagged edges (feathers, grass, railings) on the final image. The game draws its HUD and subtitles into the same image, so text edges are smoothed too. About 0.2 to 0.4 ms per frame at 1080p (RTX 2060).",
                    "Suaviza o serrilhado (penas, grama, grades) na imagem final. O jogo desenha o HUD e as legendas na mesma imagem, então as bordas do texto também são suavizadas. Cerca de 0,2 a 0,4 ms por quadro em 1080p (RTX 2060)."));
        ImGui::EndTable();
    }
    ImGui::SeparatorText(TL("Color", "Cor"));
    if (BeginRows("##color")) {
        CheckRow(TL("Color adjustments", "Ajustes de cor"), s.color_adjust,
                 TL("Brightness, contrast, saturation and gamma of the final image (the HUD included). No measurable cost.",
                    "Brilho, contraste, saturação e gama da imagem final (o HUD incluído). Sem custo mensurável."));
        ImGui::BeginDisabled(!s.color_adjust);
        FloatSliderRow(TL("Brightness", "Brilho"), s.brightness, G::Brightness, TL("Adds light or shadow evenly; 0 is unchanged.", "Clareia ou escurece por igual; 0 não altera."));
        FloatSliderRow(TL("Contrast", "Contraste"), s.contrast, G::Contrast, TL("Spreads tones away from mid gray; 1 is unchanged.", "Afasta os tons do cinza médio; 1 não altera."));
        FloatSliderRow(TL("Saturation", "Saturação"), s.saturation, G::Saturation, TL("Color intensity: 0 is black and white, 1 is unchanged.", "Intensidade das cores: 0 é preto e branco, 1 não altera."));
        FloatSliderRow(TL("Gamma", "Gama"), s.color_gamma, G::Gamma, TL("Above 1 lightens the midtones, below 1 darkens them; blacks and whites stay.", "Acima de 1 clareia os tons médios, abaixo de 1 escurece; pretos e brancos ficam."));
        ImGui::EndDisabled();
        ImGui::EndTable();
    }
    ImGui::SeparatorText(TL("Information", "Informações"));
    if (BeginRows("##image_info")) {
        char text[96];
        std::snprintf(text, sizeof(text), "%d x %d", iw, ih);
        InfoRow(TL("Game image", "Imagem do jogo"), text);
        std::snprintf(text, sizeof(text), "%d x %d", ww, wh);
        InfoRow(TL("Windowed", "Janela"), text);
        InfoRow("FSR 1", !s.fsr1 ? TL("off", "desligado") : upscaling ? TL("active", "ativo") : TL("no effect (image not smaller than window)", "sem efeito (imagem não é menor que a janela)"));
        InfoRow(TL("Sharpening", "Nitidez"), !s.rcas_applied ? TL("not applied", "não aplicada") : s.cas ? TL("applied (CAS)", "aplicada (CAS)") : TL("applied (RCAS)", "aplicada (RCAS)"));
        ImGui::EndTable();
    }
}

void PerformanceTab() {
    namespace G = TlgGraphics;
    auto& s = TlgSettings::Get();
    // tlg: GoW3's render-resolution and engine-frame-rate patches and the readback shortcuts are not
    // offered: they do not apply to TLG, and the readback ones crash it (it needs precise readbacks).
    ImGui::SeparatorText(TL("Live", "Em tempo real"));
    if (BeginRows("##live")) {
        static const char* const fps_labels[] = {"30", "60", "120", "240", TL("Unlimited", "Sem limite")};
        // tlg: the engine ceiling is the launch's frame rate mode (launcher, TLG_FPS): a limit above it
        // has no effect.
        const char* fps_tip = s.applied_engine_fps <= 30
            ? TL("Caps the presented frames. The game runs at 30 FPS (as on PS4); 60 FPS is a launcher option.",
                 "Limita os quadros apresentados. O jogo roda a 30 FPS (como no PS4); 60 FPS é uma opção do launcher.")
            : s.applied_engine_fps <= 60
            ? TL("Caps the presented frames. 60 FPS mode (launcher): limits above 60 have no effect.",
                 "Limita os quadros apresentados. Modo 60 FPS (launcher): limites acima de 60 não têm efeito.")
            : TL("Caps the presented frames. Unlocked mode (launcher): Unlimited follows the display refresh, up to 120.",
                 "Limita os quadros apresentados. Modo livre (launcher): Sem limite segue a taxa do monitor, até 120.");
        ChoiceRow(TL("Frame rate limit", "Limite de FPS"), s.fps_limit, fps_labels, G::FpsLimits.data(), int(G::FpsLimits.size()),
                  fps_tip);
        static const char* const queued_labels[] = {TL("1 (lowest latency)", "1 (menor atraso)"), "2", TL("Unlimited", "Sem limite")};
        ChoiceRow(TL("Frames queued", "Quadros na fila"), s.frames_queued, queued_labels, G::FramesQueued.data(),
                  int(G::FramesQueued.size()), TL("More frames queued: steadier FPS, slower response to input.", "Mais quadros na fila: FPS mais estável, resposta mais lenta."));
        CheckRow(TL("Compile new shaders in the background", "Compilar shaders novos em segundo plano"), s.async_shaders,
                 TL("Fewer stutters in new areas; an object or effect may appear a moment later.", "Menos engasgos em áreas novas; um objeto ou efeito pode aparecer um instante depois."));
        ImGui::EndTable();
    }
}

void OverlayTab() {
    namespace P = TlgPerfStats;
    auto& s = TlgSettings::Get();
    if (BeginRows("##overlay_on")) {
        CheckRow(TL("Show overlay (F10)", "Mostrar overlay (F10)"), s.show_fps, TL("The performance overlay in a corner of the screen.", "O overlay de desempenho num canto da tela."));
        ImGui::EndTable();
    }
    ImGui::BeginDisabled(!s.show_fps);
    ImGui::SeparatorText(TL("What to show", "O que mostrar"));
    if (ImGui::BeginTable("##overlay_items", 2, ImGuiTableFlags_SizingStretchProp)) {
        ImGui::TableNextColumn();
        static const char* const names[] = {"FPS", TL("Frametime", "Tempo de quadro"), "Upscaler", TL("GPU (name and use)", "GPU (nome e uso)"), TL("CPU (game)", "CPU (jogo)"),
                                            TL("RAM (game / total)", "RAM (jogo / total)"), TL("VRAM (used / available)", "VRAM (usada / disponível)")};
        for (unsigned item = 0; item < 7; ++item) {
            const unsigned bit = 1u << item;
            bool on = (s.overlay_items & bit) != 0;
            if (ImGui::Checkbox(names[item], &on)) {
                s.overlay_items = on ? (s.overlay_items | bit) : (s.overlay_items & ~bit);
                dirty = true;
            }
        }
        ImGui::TableNextColumn();
        ImGui::TextDisabled(TL("Preview", "Prévia"));
        ImGui::BeginChild("##preview", ImVec2(0, 0), ImGuiChildFlags_Borders | ImGuiChildFlags_AutoResizeY);
        ImGui::SetWindowFontScale(s.overlay_scale / 100.0f);
        const std::string text = OverlayText();
        ImGui::TextUnformatted(text.empty() ? TL("(nothing selected)", "(nada selecionado)") : text.c_str());
        ImGui::SetWindowFontScale(1.0f);
        ImGui::EndChild();
        ImGui::EndTable();
    }
    ImGui::SeparatorText(TL("Appearance", "Aparência"));
    if (BeginRows("##appearance")) {
        SliderRow(TL("Font size", "Tamanho da fonte"), s.overlay_scale, 50, 300, "%d%%", TL("Size of the overlay text.", "Tamanho do texto do overlay."));
        static const char* const corners[] = {TL("Top left", "Superior esquerdo"), TL("Top right", "Superior direito"), TL("Bottom left", "Inferior esquerdo"), TL("Bottom right", "Inferior direito")};
        ChoiceRow(TL("Corner", "Canto"), s.overlay_corner, corners, nullptr, 4, TL("Where the overlay sits.", "Onde o overlay fica."));
        SliderRow(TL("Background opacity", "Opacidade do fundo"), s.overlay_opacity, 0, 100, "%d%%", TL("0% is no background.", "0% é sem fundo."));
        static const char* const layouts[] = {TL("One line", "Uma linha"), TL("One item per line", "Um item por linha")};
        ChoiceRow(TL("Layout", "Disposição"), s.overlay_layout, layouts, nullptr, 2, TL("Items side by side or stacked.", "Itens lado a lado ou empilhados."));
        ImGui::EndTable();
    }
    ImGui::EndDisabled();
    ImGui::SeparatorText(TL("About", "Sobre"));
    if (BeginRows("##about")) {
        const auto& elf = Common::ElfInfo::Instance();
        char text[160];
        std::snprintf(text, sizeof(text), "%.*s v%.*s", int(elf.GameSerial().size()), elf.GameSerial().data(),
                      int(elf.AppVer().size()), elf.AppVer().data());
        InfoRow(TL("Game", "Jogo"), text);
        const u32 total = background_total;
        if (total) {
            std::snprintf(text, sizeof(text), TL("loading %u%%", "carregando %u%%"), u32(u64(background_done) * 100 / total));
        } else {
            std::snprintf(text, sizeof(text), TL("ready", "pronto"));
        }
        InfoRow(TL("Shader cache", "Cache de shaders"), text);
        ImGui::EndTable();
    }
}

// Startup options changed since this launch (applied by "Apply and restart").
// Mouse and keyboard (src/runtime_pad.c): the mouse settings apply at once; the layout is the
// default one unless the launcher's Controls (tlg.ini key_map) or TLG_KEY_MAP changed it.
void ControlsTab() {
    auto& s = TlgSettings::Get();
    ImGui::SeparatorText(TL("Mouse", "Mouse"));
    if (BeginRows("##mouse")) {
        CheckRow(TL("Mouse turns the camera", "Mouse gira a câmera"), s.mouse_enabled,
                 TL("The game window takes the mouse while it has focus. Esc releases it; a click in the window takes it back.",
                    "A janela do jogo prende o mouse enquanto tem o foco. Esc solta; um clique na janela prende de novo."));
        ImGui::BeginDisabled(!s.mouse_enabled);
        FloatRow(TL("Sensitivity", "Sensibilidade"), s.mouse_sensitivity, 0.1f, 5.0f, "%.2f",
                 TL("How far the camera turns for the same mouse movement.", "Quanto a câmera gira para o mesmo movimento do mouse."));
        CheckRow(TL("Invert Y axis", "Inverter eixo Y"), s.mouse_invert_y,
                 TL("Moving the mouse forward looks down.", "Empurrar o mouse para frente olha para baixo."));
        FloatRow(TL("Smoothing", "Suavização"), s.mouse_smoothing, 0.0f, 0.9f, "%.2f",
                 TL("Evens out the camera motion; higher values feel softer and a little slower.",
                    "Deixa o movimento da câmera mais uniforme; valores altos ficam mais suaves e um pouco mais lentos."));
        FloatRow(TL("Acceleration", "Aceleração"), s.mouse_accel, 0.0f, 2.0f, "%.2f",
                 TL("Fast movements turn more than slow ones. 0 is linear.", "Movimentos rápidos giram mais que os lentos. 0 é linear."));
        FloatRow(TL("Anti-dead zone", "Anti-zona morta"), s.mouse_deadzone, 0.0f, 0.5f, "%.2f",
                 TL("Small mouse movements skip the game's stick dead zone. Raise it if slow movements do nothing.",
                    "Movimentos pequenos do mouse pulam a zona morta do analógico do jogo. Aumente se movimentos lentos não fizerem nada."));
        ImGui::EndDisabled();
        ImGui::EndTable();
    }
    ImGui::SeparatorText(TL("Keyboard and mouse layout", "Layout de teclado e mouse"));
    if (BeginRows("##layout")) {
        InfoRow(TL("Move / camera", "Andar / câmera"), TL("WASD / mouse or arrow keys", "WASD / mouse ou setas"));
        InfoRow(TL("Jump (Cross)", "Pular (X)"), TL("Space", "Espaço"));
        InfoRow(TL("Grab, hold on (Triangle)", "Agarrar, segurar (Triângulo)"), TL("Left click or Q", "Clique esquerdo ou Q"));
        InfoRow(TL("Call Trico (R1)", "Chamar o Trico (R1)"), TL("Right click or 3", "Clique direito ou 3"));
        InfoRow(TL("Square / Circle", "Quadrado / Círculo"), TL("E or middle click / Left Shift", "E ou clique do meio / Shift esquerdo"));
        InfoRow("L1 / L2 / R2", "1 / R / F");
        InfoRow("L3 / R3", "Z / C");
        InfoRow(TL("D-pad", "Direcional"), "I J K L");
        InfoRow("Options", "Enter");
        InfoRow(TL("Touchpad (photo / pause)", "Touchpad (foto / pausa)"), "Tab / Backspace");
        InfoRow(TL("Release the mouse", "Soltar o mouse"), "Esc");
        const char* env = std::getenv("TLG_KEY_MAP");
        const std::string remap = env && env[0] ? std::string(env) : s.key_map;
        if (!remap.empty()) {
            InfoRow(TL("Remapped (launcher)", "Remapeado (launcher)"), remap.c_str());
        }
        ImGui::EndTable();
    }
    ImGui::PushTextWrapPos(0.0f);
    ImGui::TextDisabled("%s", TL("Remap keys and mouse buttons in the launcher (Controls); it applies at the next start.",
                                 "Remapeie teclas e botões do mouse no launcher (Controles); vale a partir da próxima vez que o jogo abrir."));
    ImGui::PopTextWrapPos();
}

int RestartChanges() {
    const auto& s = TlgSettings::Get();
    return (s.render_resolution != s.startup_render_resolution) + (s.engine_fps != s.startup_engine_fps) +
           (s.deferred_readback != s.startup_deferred_readback) + (s.stale_readback != s.startup_stale_readback);
}

void Menu() {
    auto& s = TlgSettings::Get();
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(ImVec2(viewport->WorkPos.x + viewport->WorkSize.x * 0.5f,
                                   viewport->WorkPos.y + viewport->WorkSize.y * 0.5f),
                            ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
    ImGui::SetNextWindowSize(ImVec2(std::min(760.0f * base_scale, viewport->WorkSize.x * 0.95f),
                                    std::min(680.0f * base_scale, viewport->WorkSize.y * 0.9f)),
                             ImGuiCond_Appearing);
    bool keep_open = true;
    // tlg: the game's own title (param.sfo), not a fixed one.
    static const std::string heading = [] {
        const std::string_view title = Common::ElfInfo::Instance().Title();
        const char* app_name = std::getenv("TLG_APP_NAME");
        return std::string(!title.empty() ? title : app_name && *app_name ? app_name : "The Last Guardian") +
               "  (Insert / R3+L2)";
    }();
    if (!ImGui::Begin(heading.c_str(), &keep_open, ImGuiWindowFlags_NoCollapse)) {
        ImGui::End();
        return;
    }
    footer_help = nullptr;
    constexpr int TabCount = 4;
    const ImGuiIO& io = ImGui::GetIO();
    if (!io.WantTextInput) {
        const int step = ImGui::IsKeyPressed(ImGuiKey_GamepadR1, false) || ImGui::IsKeyPressed(ImGuiKey_E, false) ? 1
                         : ImGui::IsKeyPressed(ImGuiKey_GamepadL1, false) || ImGui::IsKeyPressed(ImGuiKey_Q, false)
                             ? -1
                             : 0;
        if (step) {
            requested_tab = (s.menu_tab + step + TabCount) % TabCount;
        }
    }
    const float footer = ImGui::GetFrameHeightWithSpacing() * 2.0f + ImGui::GetTextLineHeightWithSpacing() * 2.0f;
    if (ImGui::BeginTabBar("##tabs")) {
        static const char* const tabs[TabCount] = {"Overlay", TL("Image", "Imagem"), TL("Performance", "Desempenho"),
                                                   TL("Controls", "Controles")};
        for (int tab = 0; tab < TabCount; ++tab) {
            const ImGuiTabItemFlags flags = requested_tab == tab ? ImGuiTabItemFlags_SetSelected : 0;
            if (!ImGui::BeginTabItem(tabs[tab], nullptr, flags)) {
                continue;
            }
            if (s.menu_tab != tab && requested_tab < 0) {
                s.menu_tab = tab;
                dirty = true;
            }
            if (ImGui::BeginChild("##body", ImVec2(0, -footer))) {
                switch (tab) {
                case 1: ImageTab(); break;
                case 2: PerformanceTab(); break;
                case 3: ControlsTab(); break;
                default: OverlayTab(); break;
                }
            }
            ImGui::EndChild();
            ImGui::EndTabItem();
        }
        if (requested_tab >= 0) {
            s.menu_tab = requested_tab;
            dirty = true;
            requested_tab = -1;
        }
        ImGui::EndTabBar();
    }

    ImGui::Separator();
    ImGui::PushTextWrapPos(0.0f);
    ImGui::TextDisabled("%s", footer_help ? footer_help : TL("L1 / R1 or Q / E: switch tabs. Settings are saved in tlg.ini.", "L1 / R1 ou Q / E: trocar de aba. As configurações ficam salvas em tlg.ini."));
    ImGui::PopTextWrapPos();
    if (const int changes = RestartChanges()) {
        ImGui::TextColored(ImVec4(0.85f, 0.72f, 0.45f, 1.0f), "%d change%s need%s a restart (unsaved progress is lost).",
                           changes, changes == 1 ? "" : "s", changes == 1 ? "s" : "");
        ImGui::SameLine();
        ImGui::BeginDisabled(!std::getenv("TLG_RESTART_COMMAND"));
        if (ImGui::Button(TL("Apply and restart", "Aplicar e reiniciar"))) {
            // The new launch confirms the options once the game shows; run.py restores the
            // previous ones if it never does (restart_unconfirmed).
            s.restart_unconfirmed = true;
            TlgSettings::Save();
            runtime_restart();
        }
        ImGui::EndDisabled();
    } else {
        ImGui::NewLine();
    }
    const float close_width = ImGui::CalcTextSize(TL("Close", "Fechar")).x + ImGui::GetStyle().FramePadding.x * 2;
    ImGui::SetCursorPosX(ImGui::GetCursorPosX() + ImGui::GetContentRegionAvail().x - close_width);
    if (ImGui::Button(TL("Close", "Fechar"))) {
        keep_open = false;
    }
    ImGui::End();
    if (!keep_open) {
        SetOpen(false);
    }
}

// The game's text dialog: what is typed, and how to finish (keyboard or controller).
void TextEntryBox() {
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(ImVec2(viewport->WorkPos.x + viewport->WorkSize.x * 0.5f,
                                   viewport->WorkPos.y + viewport->WorkSize.y * 0.42f),
                            ImGuiCond_Always, ImVec2(0.5f, 0.5f));
    ImGui::SetNextWindowSizeConstraints(ImVec2(viewport->WorkSize.x * 0.32f, 0.0f),
                                        ImVec2(viewport->WorkSize.x * 0.8f, FLT_MAX));
    ImGui::SetNextWindowBgAlpha(0.92f);
    ImGui::Begin("##text_entry", nullptr,
                 ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize |
                     ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoNav |
                     ImGuiWindowFlags_NoFocusOnAppearing);
    ImGui::TextColored(ImVec4(0.85f, 0.72f, 0.45f, 1.0f), "%s", text_entry_prompt.c_str());
    ImGui::Separator();
    ImGui::SetWindowFontScale(1.4f);
    ImGui::Text("%s_", text_entry_text.c_str());
    ImGui::SetWindowFontScale(1.0f);
    ImGui::Separator();
    ImGui::TextDisabled("Keyboard: type, Backspace to erase, Enter = OK, Esc = cancel");
    ImGui::TextDisabled("Controller: Cross (A) = OK, Circle (B) = cancel");
    ImGui::End();
}

// ---- Save dialogs: drawing. The layout is in design pixels of a 1280x720 screen, times k. ----
constexpr u32 kSaveAccent = 0x5aa9ff, kSaveText = 0xeef2f8, kSaveMuted = 0xaab5c7, kSaveDim = 0x8b97ab,
              kSavePanel = 0x141923, kSaveLine = 0x263042, kSaveCard = 0x161c28, kSaveCardOn = 0x1f2a3d,
              kSaveThumb = 0x1d2433, kSaveBorder = 0x2b3445, kSaveKnob = 0x3a4659, kSaveWarn = 0xf0a43a,
              kSaveOk = 0x4fd1a5;

ImU32 SaveColor(u32 rgb, float alpha = 1.0f) {
    return IM_COL32(rgb >> 16, (rgb >> 8) & 255, rgb & 255, int(std::clamp(alpha, 0.0f, 1.0f) * 255.0f));
}

struct SavePainter {
    ImDrawList* dl;
    ImFont* font;
    float k;
    ImVec2 at; // the panel's top-left corner, in display pixels

    ImVec2 P(float x, float y) const { return ImVec2(at.x + x * k, at.y + y * k); }
    float Width(float size, const std::string& text) const {
        return font->CalcTextSizeA(size * k, FLT_MAX, 0.0f, text.c_str()).x / k;
    }
    // The text cut with "..." to fit `width` design pixels.
    std::string Fit(float size, const std::string& text, float width) const {
        if (Width(size, text) <= width) return text;
        std::string cut = text;
        while (!cut.empty()) {
            while (!cut.empty() && (u8(cut.back()) & 0xc0) == 0x80) cut.pop_back(); // UTF-8 tail
            if (!cut.empty()) cut.pop_back();
            if (Width(size, cut + "...") <= width) return cut + "...";
        }
        return "...";
    }
    // Text at (x, y) design pixels; bold is drawn twice, a hair apart (one embedded face).
    void Text(float x, float y, float size, u32 rgb, const std::string& text, bool bold = false,
              float alpha = 1.0f, float wrap = 0.0f) const {
        const ImU32 col = SaveColor(rgb, alpha);
        dl->AddText(font, size * k, P(x, y), col, text.c_str(), nullptr, wrap * k);
        if (bold) dl->AddText(font, size * k, P(x + 0.55f, y), col, text.c_str(), nullptr, wrap * k);
    }
    void TextRight(float right, float y, float size, u32 rgb, const std::string& text, bool bold = false) const {
        Text(right - Width(size, text), y, size, rgb, text, bold);
    }
    void Box(float x0, float y0, float x1, float y1, u32 fill, float rounding, float alpha = 1.0f) const {
        dl->AddRectFilled(P(x0, y0), P(x1, y1), SaveColor(fill, alpha), rounding * k);
    }
    void Frame(float x0, float y0, float x1, float y1, u32 rgb, float rounding, float thickness,
               float alpha = 1.0f) const {
        dl->AddRect(P(x0, y0), P(x1, y1), SaveColor(rgb, alpha), rounding * k, 0, thickness * k);
    }
    void Line(float x0, float y0, float x1, float y1, u32 rgb, float thickness, float alpha = 1.0f) const {
        dl->AddLine(P(x0, y0), P(x1, y1), SaveColor(rgb, alpha), thickness * k);
    }
    // A controller button: 0 Cross (confirm), 1 Circle (back), centred at (x, y).
    void Button(float x, float y, int which) const {
        const ImVec2 c = P(x, y);
        dl->AddCircleFilled(c, 11.0f * k, SaveColor(kSaveThumb));
        dl->AddCircle(c, 11.0f * k, SaveColor(kSaveKnob), 0, 1.0f * k);
        if (which == 0) {
            Line(x - 4, y - 4, x + 4, y + 4, 0x8fb6ff, 2.0f);
            Line(x + 4, y - 4, x - 4, y + 4, 0x8fb6ff, 2.0f);
        } else {
            dl->AddCircle(c, 5.0f * k, SaveColor(0xff8a8a), 0, 2.0f * k);
        }
    }
    // The panel itself: shadow, fill, border; then the discreet credit under its right corner.
    void Panel(float w, float h) const {
        dl->AddRectFilled(P(0, 18), P(w, h + 18), SaveColor(0x000000, 0.35f), 18.0f * k);
        Box(0, 0, w, h, kSavePanel, 18.0f, 0.97f);
        Frame(0, 0, w, h, kSaveBorder, 18.0f, 1.0f);
        const std::string credit = "@hayatog-dev";
        Text(w - 6.0f - Width(11.0f, credit), h + 10.0f, 11.0f, 0x4a5568, credit);
    }
    // A save's picture (16:9) or a placeholder; `is_new` draws the dashed "+" slot.
    void Picture(float x, float y, float w, float h, ImTextureData* tex, bool is_new) const {
        if (tex) {
            dl->AddImageRounded(tex->GetTexRef(), P(x, y), P(x + w, y + h), ImVec2(0, 0), ImVec2(1, 1),
                                IM_COL32_WHITE, 10.0f * k);
            Frame(x, y, x + w, y + h, 0x323d52, 10.0f, 1.0f);
            return;
        }
        if (is_new) {
            for (float t = 0; t < 1.0f; t += 0.1f) { // dashes around the slot
                Line(x + w * t, y, x + w * (t + 0.05f), y, kSaveKnob, 2.0f);
                Line(x + w * t, y + h, x + w * (t + 0.05f), y + h, kSaveKnob, 2.0f);
            }
            for (float t = 0; t < 1.0f; t += 0.18f) {
                Line(x, y + h * t, x, y + h * (t + 0.09f), kSaveKnob, 2.0f);
                Line(x + w, y + h * t, x + w, y + h * (t + 0.09f), kSaveKnob, 2.0f);
            }
            Line(x + w / 2, y + h / 2 - 11, x + w / 2, y + h / 2 + 11, kSaveDim, 2.0f);
            Line(x + w / 2 - 11, y + h / 2, x + w / 2 + 11, y + h / 2, kSaveDim, 2.0f);
            return;
        }
        Box(x, y, x + w, y + h, kSaveThumb, 10.0f);
        Frame(x, y, x + w, y + h, 0x323d52, 10.0f, 1.0f);
    }
};

SavePainter SavePainterFor(float w, float h) {
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    // 720p design scaled to the display, kept inside the screen on narrow windows.
    const float k = std::min(viewport->WorkSize.y / 720.0f, viewport->WorkSize.x * 0.94f / w);
    SavePainter p{ImGui::GetForegroundDrawList(), ImGui::GetFont(), k, {}};
    p.at = ImVec2(viewport->WorkPos.x + (viewport->WorkSize.x - w * k) * 0.5f,
                  viewport->WorkPos.y + (viewport->WorkSize.y - h * k) * 0.5f);
    return p;
}

void SaveBackdrop(float alpha) {
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::GetForegroundDrawList()->AddRectFilled(
        viewport->WorkPos, ImVec2(viewport->WorkPos.x + viewport->WorkSize.x, viewport->WorkPos.y + viewport->WorkSize.y),
        SaveColor(0x05070c, alpha));
}

std::string SaveWhen(s64 mtime) {
    if (mtime <= 0) return {};
    const time_t t = time_t(mtime);
    std::tm tm{};
#ifdef _WIN32
    localtime_s(&tm, &t);
#else
    localtime_r(&t, &tm);
#endif
    char out[64];
    if (UiPortuguese()) {
        std::snprintf(out, sizeof(out), "%02d/%02d/%04d · %02d:%02d", tm.tm_mday, tm.tm_mon + 1,
                      tm.tm_year + 1900, tm.tm_hour, tm.tm_min);
    } else {
        static const char* months[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
        const int hour = tm.tm_hour % 12 ? tm.tm_hour % 12 : 12;
        std::snprintf(out, sizeof(out), "%s %d, %d · %d:%02d %s", months[tm.tm_mon % 12], tm.tm_mday,
                      tm.tm_year + 1900, hour, tm.tm_min, tm.tm_hour < 12 ? "AM" : "PM");
    }
    return out;
}

std::string SaveAgo(s64 mtime) {
    const s64 seconds = s64(std::time(nullptr)) - mtime;
    if (mtime <= 0 || seconds < 0) return {};
    const bool pt = UiPortuguese();
    char out[64];
    if (seconds < 60) return pt ? "agora mesmo" : "just now";
    if (seconds < 3600) {
        const int m = int(seconds / 60);
        std::snprintf(out, sizeof(out), pt ? (m == 1 ? "há %d minuto" : "há %d minutos")
                                           : (m == 1 ? "%d minute ago" : "%d minutes ago"), m);
    } else if (seconds < 86400) {
        const int h = int(seconds / 3600);
        std::snprintf(out, sizeof(out), pt ? (h == 1 ? "há %d hora" : "há %d horas")
                                           : (h == 1 ? "%d hour ago" : "%d hours ago"), h);
    } else {
        const int d = int(seconds / 86400);
        if (d == 1) return pt ? "ontem" : "yesterday";
        std::snprintf(out, sizeof(out), pt ? "há %d dias" : "%d days ago", d);
    }
    return out;
}

std::string SaveSize(u64 bytes) {
    if (!bytes) return {};
    char out[32];
    if (bytes < 1024 * 1024) {
        std::snprintf(out, sizeof(out), "%llu KB", (unsigned long long)((bytes + 1023) / 1024));
    } else {
        std::snprintf(out, sizeof(out), "%.1f MB", double(bytes) / (1024.0 * 1024.0));
        if (UiPortuguese()) {
            for (char* c = out; *c; ++c) if (*c == '.') *c = ',';
        }
    }
    return out;
}

const char* SaveTitle(int kind) {
    return kind == 2 ? TL("Load game", "Carregar jogo") : kind == 3 ? TL("Delete save", "Excluir save")
                                                         : TL("Save game", "Salvar jogo");
}

ImTextureData* SaveTexture(size_t i) {
    return i < choice_textures.size() ? choice_textures[i] : nullptr;
}

// One save as a card: picture, the game's title and text, when it was saved.
void SaveCard(const SavePainter& p, float x0, float y0, float x1, const SaveRow& row, ImTextureData* tex,
              bool selected, float picture_w) {
    const float picture_h = picture_w * 9.0f / 16.0f, h = picture_h + 24.0f;
    if (selected) {
        p.Frame(x0 - 3, y0 - 3, x1 + 3, y0 + h + 3, kSaveAccent, 16.0f, 4.0f, 0.12f);
        p.Box(x0, y0, x1, y0 + h, kSaveCardOn, 14.0f);
        p.Frame(x0, y0, x1, y0 + h, kSaveAccent, 14.0f, 2.0f);
    } else {
        p.Box(x0, y0, x1, y0 + h, kSaveCard, 14.0f);
    }
    p.Picture(x0 + 16, y0 + 12, picture_w, picture_h, tex, row.is_new);
    const float text_x = x0 + 16 + picture_w + 18;
    std::string when, ago;
    if (row.is_new) {
        p.Text(text_x, y0 + h / 2 - 20, 17.0f, kSaveText, TL("New save", "Novo save"), true);
        p.Text(text_x, y0 + h / 2 + 4, 13.5f, kSaveMuted, TL("Create a new save", "Criar um save novo"));
        return;
    }
    when = SaveWhen(row.mtime);
    ago = SaveAgo(row.mtime);
    const std::string size = SaveSize(row.bytes);
    if (!size.empty()) ago = ago.empty() ? size : ago + " · " + size;
    const float right = x1 - 16;
    const float right_w = std::max(p.Width(14.0f, when), p.Width(12.5f, ago));
    const float text_w = right - text_x - (right_w > 0 ? right_w + 20 : 0);
    std::string line = row.subtitle;
    if (!row.detail.empty()) line = line.empty() ? row.detail : line + " · " + row.detail;
    for (char& c : line) if (c == '\n' || c == '\r') c = ' ';
    p.Text(text_x, y0 + h / 2 - 20, 17.0f, kSaveText, p.Fit(17.0f, row.title, text_w), true);
    p.Text(text_x, y0 + h / 2 + 4, 13.5f, kSaveMuted, p.Fit(13.5f, line, text_w));
    p.TextRight(right, y0 + h / 2 - 18, 14.0f, 0xdfe6f1, when, true);
    p.TextRight(right, y0 + h / 2 + 5, 12.5f, kSaveDim, ago);
}

void SaveListBox() {
    const int count = int(save_rows.size());
    const int shown = std::min(count, 4);
    const float w = 880, row_h = 96, gap = 10, header_h = 78, footer_h = 54, pad = 18;
    const float list_h = shown * row_h + std::max(shown - 1, 0) * gap + pad * 2;
    const float h = header_h + list_h + footer_h;
    SaveBackdrop(0.62f);
    SavePainter p = SavePainterFor(w, h);
    p.Panel(w, h);

    // Header: a floppy, the title, the game and the number of saves.
    const float ix = 28, iy = 25;
    p.Frame(ix, iy, ix + 26, iy + 26, kSaveAccent, 4.0f, 1.8f);
    p.Frame(ix + 6, iy, ix + 20, iy + 9, kSaveAccent, 1.0f, 1.8f);
    p.Frame(ix + 6, iy + 15, ix + 20, iy + 26, kSaveAccent, 1.0f, 1.8f);
    p.Text(70, 18, 24.0f, kSaveText, SaveTitle(save_kind), true);
    const int saves = count - int(std::count_if(save_rows.begin(), save_rows.end(), [](const SaveRow& r) { return r.is_new; }));
    char sub[160];
    const char* game = std::getenv("TLG_APP_NAME");
    std::snprintf(sub, sizeof(sub), "%s%s%d %s", game && *game ? game : "", game && *game ? " · " : "", saves,
                  saves == 1 ? "save" : "saves");
    p.Text(70, 48, 13.0f, kSaveDim, sub);
    p.Line(0, header_h, w, header_h, kSaveLine, 1.0f);

    // Rows, scrolled so the selected one is shown.
    if (choice_index < choice_first) choice_first = choice_index;
    if (choice_index >= choice_first + shown) choice_first = choice_index - shown + 1;
    choice_first = std::clamp(choice_first, 0, std::max(count - shown, 0));
    save_row_rects.assign(count, ImRect());
    for (int i = choice_first; i < choice_first + shown; ++i) {
        const float y = header_h + pad + (i - choice_first) * (row_h + gap);
        SaveCard(p, 20, y, w - 20, save_rows[i], SaveTexture(size_t(i)), i == choice_index, 128.0f);
        save_row_rects[i] = ImRect(p.P(20, y), p.P(w - 20, y + row_h));
    }
    if (count > shown) { // scroll bar
        const float track = list_h - pad * 2, y0 = header_h + pad;
        const float knob = track * shown / count, top = y0 + track * choice_first / count;
        p.Box(w - 11, y0, w - 8, y0 + track, kSaveLine, 2.0f);
        p.Box(w - 11, top, w - 8, top + knob, kSaveDim, 2.0f);
    }

    // Footer: what the buttons do.
    const float fy = header_h + list_h;
    p.Line(0, fy, w, fy, kSaveLine, 1.0f);
    const char* confirm = save_kind == 2 ? TL("Load", "Carregar") : save_kind == 3 ? TL("Delete", "Excluir")
                                                                                  : TL("Save here", "Salvar aqui");
    float x = 40;
    p.Button(x, fy + footer_h / 2, 0);
    p.Text(x + 18, fy + footer_h / 2 - 9, 13.5f, 0xb8c2d3, confirm);
    x += 18 + p.Width(13.5f, confirm) + 34;
    p.Button(x, fy + footer_h / 2, 1);
    p.Text(x + 18, fy + footer_h / 2 - 9, 13.5f, 0xb8c2d3, TL("Back", "Voltar"));
    p.TextRight(w - 28, fy + footer_h / 2 - 8, 12.5f, 0x7f8ba0,
                TL("Enter / click: choose · Esc / right click: back", "Enter / clique: escolher · Esc / botão direito: voltar"));
}

// The message's words for a system message type (sceSaveDataDialog), the game's own text or an
// error code. warn: drawn with the warning sign.
struct SaveMessageWords {
    std::string title, body;
    int buttons; // 0 OK, 1 yes/no, 3 OK/cancel
    bool warn;
};

SaveMessageWords SaveMessageFor(int kind, int code, u64 value, const std::string& text) {
    const bool pt = UiPortuguese();
    switch (code) {
    case 1:
        return {TL("No saved data", "Nenhum save encontrado"),
                TL("There is no saved data to load.", "Não há nenhum save para carregar."), 0, false};
    case 2:
        if (kind == 2) return {TL("Load this save?", "Carregar este save?"),
                               TL("Progress that was not saved will be lost.", "O progresso não salvo será perdido."), 1, false};
        if (kind == 3) return {TL("Delete this save?", "Excluir este save?"),
                               TL("This cannot be undone.", "Não dá para desfazer."), 1, true};
        return {TL("Save the game?", "Salvar o jogo?"), TL("A new save will be created.", "Um save novo será criado."), 1, false};
    case 3:
        return {TL("Overwrite this save?", "Sobrescrever este save?"),
                TL("The current progress will replace this save. This cannot be undone.",
                   "O progresso atual vai substituir este save. Não dá para desfazer."), 1, true};
    case 4:
    case 8:
        return {TL("Not enough space", "Sem espaço suficiente"),
                TL("Free some disk space and try again.", "Libere espaço no disco e tente de novo."), 0, true};
    case 6:
        return {TL("This save is damaged", "Este save está corrompido"),
                TL("It cannot be used.", "Não dá para usar este save."), 0, true};
    case 10:
        return {TL("A damaged save was found", "Um save corrompido foi encontrado"),
                TL("It was deleted.", "Ele foi excluído."), 0, true};
    case 11:
        return {TL("A damaged save was found", "Um save corrompido foi encontrado"),
                TL("A new save was created in its place.", "Um save novo foi criado no lugar."), 0, true};
    case 13:
        return {TL("A damaged save was found", "Um save corrompido foi encontrado"),
                TL("It was restored.", "Ele foi restaurado."), 0, true};
    case 14:
        return {TL("The saves are too large", "Os saves estão grandes demais"),
                TL("Delete some saves and try again.", "Exclua alguns saves e tente de novo."), 0, true};
    case 100:
        return {SaveTitle(kind), text, 0, false};
    case 101: {
        char body[96];
        std::snprintf(body, sizeof(body), pt ? "Código do erro: 0x%08X" : "Error code: 0x%08X", unsigned(value));
        return {TL("Save data error", "Erro nos dados salvos"), body, 0, true};
    }
    default:
        return {SaveTitle(kind), text, 0, false};
    }
}

void SaveMessageBox() {
    const SaveMessageWords words = SaveMessageFor(save_kind, message_code, message_value, message_text);
    const int buttons = message_buttons >= 0 ? message_buttons : words.buttons;
    const float w = 560, pad = 28, inner = w - pad * 2;
    // Height: title, the save's card, the wrapped text, the buttons.
    ImFont* font = ImGui::GetFont();
    const float k0 = std::min(ImGui::GetMainViewport()->WorkSize.y / 720.0f,
                              ImGui::GetMainViewport()->WorkSize.x * 0.94f / w);
    const float body_h = words.body.empty() ? 0.0f
        : font->CalcTextSizeA(14.5f * k0, FLT_MAX, inner * k0, words.body.c_str()).y / k0;
    const float card_h = message_has_entry ? 87.0f : 0.0f;
    float h = pad + 30 + 20 + (card_h ? card_h + 20 : 0) + (body_h ? body_h + 20 : 0) + 46 + pad;
    SaveBackdrop(0.72f);
    SavePainter p = SavePainterFor(w, h);
    p.Panel(w, h);

    float y = pad;
    if (words.warn) { // triangle
        const ImVec2 a = p.P(pad + 13, y + 2), b = p.P(pad + 26, y + 26), c = p.P(pad, y + 26);
        p.dl->AddTriangle(a, b, c, SaveColor(kSaveWarn), 2.0f * p.k);
        p.Line(pad + 13, y + 11, pad + 13, y + 18, kSaveWarn, 2.0f);
        p.dl->AddCircleFilled(p.P(pad + 13, y + 22), 1.4f * p.k, SaveColor(kSaveWarn));
    } else {
        p.dl->AddCircle(p.P(pad + 13, y + 14), 12.0f * p.k, SaveColor(kSaveAccent), 0, 2.0f * p.k);
        p.Text(pad + 8.5f, y + 4, 16.0f, kSaveAccent, "?", true);
    }
    p.Text(pad + 40, y + 1, 22.0f, kSaveText, p.Fit(22.0f, words.title, inner - 40), true);
    y += 30 + 20;
    if (message_has_entry) {
        p.Box(pad, y, w - pad, y + card_h, kSaveCard, 14.0f);
        p.Frame(pad, y, w - pad, y + card_h, kSaveBorder, 14.0f, 1.0f);
        p.Picture(pad + 14, y + 12, 112, 63, SaveTexture(0), message_entry.is_new);
        const float tx = pad + 14 + 112 + 16, tw = w - pad - 14 - tx;
        std::string line = message_entry.subtitle;
        if (!message_entry.detail.empty()) line = line.empty() ? message_entry.detail : line + " · " + message_entry.detail;
        for (char& c : line) if (c == '\n' || c == '\r') c = ' ';
        std::string when = SaveWhen(message_entry.mtime);
        const std::string ago = SaveAgo(message_entry.mtime);
        if (!when.empty() && !ago.empty()) when += " (" + ago + ")";
        p.Text(tx, y + 16, 16.0f, kSaveText,
               p.Fit(16.0f, message_entry.is_new ? std::string(TL("New save", "Novo save")) : message_entry.title, tw), true);
        p.Text(tx, y + 39, 13.0f, kSaveMuted, p.Fit(13.0f, line, tw));
        p.Text(tx, y + 59, 12.5f, kSaveDim, p.Fit(12.5f, when, tw));
        y += card_h + 20;
    }
    if (body_h) {
        p.Text(pad, y, 14.5f, 0xc3ccdb, words.body, false, 1.0f, inner);
        y += body_h + 20;
    }

    // Buttons, right-aligned: [no/cancel] [yes/OK]; the focused one is filled.
    const char* yes = buttons == 1 ? TL("Yes", "Sim") : "OK";
    const char* no = buttons == 1 ? TL("No", "Não") : TL("Cancel", "Cancelar");
    const bool two = buttons == 1 || buttons == 3;
    if (!two) message_focus = 1;
    float right = w - pad;
    save_button_rects[0] = save_button_rects[1] = ImRect();
    for (int b = 1; b >= (two ? 0 : 1); --b) {
        const char* label = b == 1 ? yes : no;
        const float bw = 22 + 20 + 10 + p.Width(15.0f, label) + 22, x0 = right - bw;
        const bool focused = b == message_focus;
        p.Box(x0, y, right, y + 46, focused ? kSaveAccent : kSaveCard, 12.0f);
        if (!focused) p.Frame(x0, y, right, y + 46, kSaveKnob, 12.0f, 1.0f);
        p.Button(x0 + 32, y + 23, b == 1 ? 0 : 1);
        p.Text(x0 + 52, y + 13, 15.0f, focused ? 0x0b0e14 : 0xdfe6f1, label, true);
        save_button_rects[b] = ImRect(p.P(x0, y), p.P(right, y + 46));
        right = x0 - 12;
    }
}

void SaveProgressBox(SaveClock::time_point now) {
    const float w = 520, h = 140;
    SaveBackdrop(0.45f);
    SavePainter p = SavePainterFor(w, h);
    p.Panel(w, h);
    // A spinning arc.
    const float t = std::chrono::duration<float>(now - progress_since).count();
    const ImVec2 c = p.P(28 + 13, 26 + 13);
    p.dl->PathArcTo(c, 11.0f * p.k, t * 6.0f, t * 6.0f + 4.4f, 24);
    p.dl->PathStroke(SaveColor(kSaveAccent), 0, 2.4f * p.k);
    const char* title = progress_kind == 2 ? TL("Loading...", "Carregando...")
                        : progress_kind == 3 ? TL("Deleting...", "Excluindo...")
                                             : TL("Saving...", "Salvando...");
    p.Text(66, 20, 21.0f, kSaveText, title, true);
    p.Text(66, 47, 13.0f, kSaveDim, TL("Do not close the game.", "Não feche o jogo."));
    const float bx0 = 28, bx1 = w - 28, by = 84;
    p.Box(bx0, by, bx1, by + 10, kSaveThumb, 5.0f);
    if (progress_percent >= 0) {
        const float f = std::clamp(progress_percent, 0, 100) / 100.0f;
        if (f > 0) p.Box(bx0, by, bx0 + (bx1 - bx0) * f, by + 10, kSaveAccent, 5.0f);
        char pct[16];
        std::snprintf(pct, sizeof(pct), "%d%%", std::clamp(progress_percent, 0, 100));
        p.TextRight(bx1, by + 20, 13.0f, 0xdfe6f1, pct, true);
    } else { // no figure: a segment sweeps the bar
        const float span = (bx1 - bx0) * 0.3f, phase = std::fmod(t * 0.8f, 1.0f);
        const float s0 = bx0 + (bx1 - bx0 + span) * phase - span;
        p.Box(std::max(s0, bx0), by, std::min(s0 + span, bx1), by + 10, kSaveAccent, 5.0f);
    }
    if (!progress_text.empty()) {
        std::string text = progress_text;
        for (char& ch : text) if (ch == '\n' || ch == '\r') ch = ' ';
        p.Text(bx0, by + 20, 13.0f, kSaveMuted, p.Fit(13.0f, text, bx1 - bx0 - 60));
    }
}

void SaveToastBox(SaveClock::time_point now) {
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    const char* text = toast_kind == 2 ? TL("Save loaded", "Save carregado")
                       : toast_kind == 3 ? TL("Save deleted", "Save excluído")
                                         : TL("Game saved", "Jogo salvo");
    const float in = std::chrono::duration<float>(now - toast_since).count();
    const float out = std::chrono::duration<float>(toast_until - now).count();
    const float alpha = std::clamp(std::min(in / 0.15f, out / 0.4f), 0.0f, 1.0f);
    const float k = viewport->WorkSize.y / 720.0f;
    SavePainter p{ImGui::GetForegroundDrawList(), ImGui::GetFont(), k, {}};
    const float w = 18 + 22 + 12 + p.Width(14.0f, text) + 20, h = 46;
    p.at = ImVec2(viewport->WorkPos.x + viewport->WorkSize.x - (32 + w) * k,
                  viewport->WorkPos.y + viewport->WorkSize.y - (28 + h) * k);
    p.Box(0, 0, w, h, kSavePanel, 14.0f, 0.92f * alpha);
    p.Frame(0, 0, w, h, kSaveBorder, 14.0f, 1.0f, alpha);
    p.Line(18, 24, 24, 30, kSaveOk, 2.4f, alpha); // a check mark
    p.Line(24, 30, 36, 17, kSaveOk, 2.4f, alpha);
    p.Text(52, 14, 14.0f, kSaveText, text, true, alpha);
}

// Present thread, imgui_mutex held, after NewFrame: whichever save dialog is up.
void SaveDialogs() {
    const auto now = SaveClock::now();
    if (choice_active) {
        SaveListBox();
    } else if (message_active) {
        SaveMessageBox();
    } else if (progress_on || now < progress_until) {
        SaveProgressBox(now);
    }
    if (now < toast_until && !choice_active && !message_active) {
        SaveToastBox(now);
    }
}

void LoadingScreen() {
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(ImVec2(viewport->WorkPos.x + viewport->WorkSize.x * 0.5f,
                                   viewport->WorkPos.y + viewport->WorkSize.y * 0.5f),
                            ImGuiCond_Always, ImVec2(0.5f, 0.5f));
    ImGui::SetNextWindowSize(ImVec2(viewport->WorkSize.x * 0.4f, 0.0f), ImGuiCond_Always);
    ImGui::SetNextWindowBgAlpha(0.0f);
    ImGui::Begin("##loading", nullptr,
                 ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoInputs |
                     ImGuiWindowFlags_NoNav | ImGuiWindowFlags_NoFocusOnAppearing);
    const u32 done = loading_done, total = loading_total;
    ImGui::SetWindowFontScale(1.6f);
    ImGui::TextUnformatted(total ? "Loading shader cache..." : "Preparing graphics...");
    ImGui::SetWindowFontScale(1.0f);
    if (total) {
        char count[64];
        std::snprintf(count, sizeof(count), "%u / %u (%u%%)", done, total,
                      u32(u64(done) * 100 / total));
        ImGui::ProgressBar(float(done) / float(total), ImVec2(-1.0f, 0.0f), count);
    }
    ImGui::TextDisabled("The first start after an update takes longer.");
    ImGui::End();
}

void FpsCounter() {
    const auto& s = TlgSettings::Get();
    const std::string text = OverlayText();
    if (text.empty()) {
        return;
    }
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    const float pad = 12.0f * base_scale;
    const int corner = s.overlay_corner;
    const bool right = corner == 1 || corner == 3, bottom = corner >= 2;
    ImGui::SetNextWindowPos(ImVec2(right ? viewport->WorkPos.x + viewport->WorkSize.x - pad : viewport->WorkPos.x + pad,
                                   bottom ? viewport->WorkPos.y + viewport->WorkSize.y - pad : viewport->WorkPos.y + pad),
                            ImGuiCond_Always, ImVec2(right ? 1.0f : 0.0f, bottom ? 1.0f : 0.0f));
    ImGui::SetNextWindowBgAlpha(s.overlay_opacity / 100.0f);
    ImGui::Begin("##fps", nullptr,
                 ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize |
                     ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoNav |
                     ImGuiWindowFlags_NoFocusOnAppearing);
    ImGui::SetWindowFontScale(s.overlay_scale / 100.0f);
    ImGui::TextUnformatted(text.c_str());
    ImGui::End();
}

std::string notice_text;
std::chrono::steady_clock::time_point notice_until;

void NoticeBox() {
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(ImVec2(viewport->WorkPos.x + viewport->WorkSize.x * 0.5f,
                                   viewport->WorkPos.y + 40.0f * base_scale),
                            ImGuiCond_Always, ImVec2(0.5f, 0.0f));
    ImGui::SetNextWindowBgAlpha(0.75f);
    ImGui::Begin("##notice", nullptr,
                 ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize |
                     ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoNav |
                     ImGuiWindowFlags_NoFocusOnAppearing);
    ImGui::SetWindowFontScale(1.3f);
    ImGui::TextUnformatted(notice_text.c_str());
    ImGui::End();
}

void BackgroundLoading() {
    const u32 done = background_done, total = std::max(background_total.load(), 1u);
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    const float pad = 12.0f * base_scale;
    ImGui::SetNextWindowPos(ImVec2(viewport->WorkPos.x + pad,
                                   viewport->WorkPos.y + viewport->WorkSize.y - pad),
                            ImGuiCond_Always, ImVec2(0.0f, 1.0f));
    ImGui::SetNextWindowBgAlpha(0.35f);
    ImGui::Begin("##background_loading", nullptr,
                 ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize |
                     ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoNav |
                     ImGuiWindowFlags_NoFocusOnAppearing);
    ImGui::TextDisabled("Loading shader cache %u%%", u32(u64(done) * 100 / total));
    ImGui::End();
}

} // namespace

void Init(const Vulkan::Instance& instance, vk::Format format, u32 image_count) {
    std::scoped_lock lock{imgui_mutex};
    if (initialized) {
        return;
    }
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.IniFilename = nullptr; // window positions are not kept
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard | ImGuiConfigFlags_NavEnableGamepad;
    io.BackendFlags |= ImGuiBackendFlags_HasGamepad;
    io.BackendPlatformName = "tlg";

    ImGui::StyleColorsDark();
    ImGuiStyle& style = ImGui::GetStyle();
    style.WindowRounding = 6.0f;
    style.FrameRounding = 4.0f;
    style.GrabRounding = 4.0f;
    style.Colors[ImGuiCol_WindowBg].w = 0.92f;

    ImFontConfig font_config;
    font_config.FontDataOwnedByAtlas = false;
    io.Fonts->AddFontFromMemoryTTF(const_cast<unsigned char*>(tlg_font_ttf),
                                   int(tlg_font_ttf_end - tlg_font_ttf), 18.0f, &font_config);

    const vk::Instance vk_instance = instance.GetInstance();
    ImGui_ImplVulkan_LoadFunctions(
        instance.ApiVersion(),
        [](const char* name, void* user) {
            return VULKAN_HPP_DEFAULT_DISPATCHER.vkGetInstanceProcAddr(
                *static_cast<const vk::Instance*>(user), name);
        },
        const_cast<vk::Instance*>(&vk_instance));

    const VkFormat color_format = static_cast<VkFormat>(format);
    ImGui_ImplVulkan_InitInfo info{};
    info.ApiVersion = instance.ApiVersion();
    info.Instance = vk_instance;
    info.PhysicalDevice = instance.GetPhysicalDevice();
    info.Device = instance.GetDevice();
    info.QueueFamily = instance.GetGraphicsQueueFamilyIndex();
    info.Queue = instance.GetGraphicsQueue();
    // Font atlas plus the save list pictures (up to 33, and a closed list's until freed).
    info.DescriptorPoolSize = 128;
    info.MinImageCount = std::max(image_count, 2u);
    info.ImageCount = std::max(image_count, 2u);
    info.UseDynamicRendering = true;
    info.PipelineInfoMain.PipelineRenderingCreateInfo = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO_KHR,
        .colorAttachmentCount = 1,
        .pColorAttachmentFormats = &color_format,
    };
    if (!ImGui_ImplVulkan_Init(&info)) {
        std::printf("Overlay: ImGui Vulkan backend init failed\n");
        ImGui::DestroyContext();
        return;
    }
    overlay_instance = &instance;
    initialized = true;
    std::printf("Overlay: menu ready (Insert or R3+L2)\n");
}

void UpdateTextInput(SDL_Window* window) {
    bool want = false;
    {
        std::scoped_lock lock{imgui_mutex};
        want = initialized && menu_open && ImGui::GetIO().WantTextInput;
    }
    if (want != SDL_TextInputActive(window)) {
        if (want) {
            SDL_StartTextInput(window);
        } else {
            SDL_StopTextInput(window);
        }
    }
}

// imgui_mutex held. The backend frees a texture some frames after its last use.
void RetireChoiceTextures() {
    for (ImTextureData* tex : choice_textures) {
        if (tex) {
            tex->WantDestroyNextFrame = true;
            choice_retired.push_back(tex);
        }
    }
    choice_textures.clear();
    choice_pictures.clear();
    choice_retiring = !choice_retired.empty();
}

// imgui_mutex held, before NewFrame: new pictures become textures, destroyed ones are freed.
void UpdateChoiceTextures() {
    if (!choice_pictures.empty()) {
        choice_textures.assign(choice_pictures.size(), nullptr);
        for (size_t i = 0; i < choice_pictures.size(); ++i) {
            const TlgPng::Image& picture = choice_pictures[i];
            if (picture.rgba.empty()) {
                continue;
            }
            ImTextureData* tex = IM_NEW(ImTextureData)();
            tex->Create(ImTextureFormat_RGBA32, picture.width, picture.height);
            std::memcpy(tex->GetPixels(), picture.rgba.data(), picture.rgba.size());
            ImGui::RegisterUserTexture(tex);
            choice_textures[i] = tex;
        }
        choice_pictures.clear();
    }
    std::erase_if(choice_retired, [](ImTextureData* tex) {
        if (tex->Status != ImTextureStatus_Destroyed) {
            return false;
        }
        ImGui::UnregisterUserTexture(tex);
        IM_DELETE(tex);
        return true;
    });
    choice_retiring = !choice_retired.empty();
}

void FinishSaveDialog() {
    RetireChoiceTextures();
    ImGui::GetIO().MouseDrawCursor = menu_open;
}

// The save list and messages take the keys, buttons and mouse that answer them; the rest stays
// with the game (held neutral by CapturesInput).
bool HandleSaveEvent(const SDL_Event& event) {
    int move = 0, finish = 0; // finish: 1 accept, 2 back
    bool moved = false, click = false;
    switch (event.type) {
    case SDL_EVENT_KEY_DOWN: {
        const SDL_Keycode key = event.key.key;
        move = key == SDLK_UP || key == SDLK_W || key == SDLK_LEFT || key == SDLK_A ? -1
               : key == SDLK_DOWN || key == SDLK_S || key == SDLK_RIGHT || key == SDLK_D ? 1
                                                                                      : 0;
        finish = key == SDLK_RETURN || key == SDLK_KP_ENTER || key == SDLK_SPACE ? 1
                 : key == SDLK_ESCAPE || key == SDLK_BACKSPACE                   ? 2
                                                                                 : 0;
        break;
    }
    case SDL_EVENT_GAMEPAD_BUTTON_DOWN: {
        const u8 button = event.gbutton.button;
        move = button == SDL_GAMEPAD_BUTTON_DPAD_UP || button == SDL_GAMEPAD_BUTTON_DPAD_LEFT ? -1
               : button == SDL_GAMEPAD_BUTTON_DPAD_DOWN || button == SDL_GAMEPAD_BUTTON_DPAD_RIGHT ? 1
                                                                                                  : 0;
        finish = button == SDL_GAMEPAD_BUTTON_SOUTH ? 1 : button == SDL_GAMEPAD_BUTTON_EAST ? 2 : 0;
        break;
    }
    case SDL_EVENT_MOUSE_MOTION: {
        const float density = PixelDensity(event.motion.windowID);
        save_mouse = ImVec2(event.motion.x * density, event.motion.y * density);
        ImGui::GetIO().AddMousePosEvent(save_mouse.x, save_mouse.y);
        moved = true;
        break;
    }
    case SDL_EVENT_MOUSE_BUTTON_DOWN:
        click = event.button.button == SDL_BUTTON_LEFT;
        finish = event.button.button == SDL_BUTTON_RIGHT ? 2 : 0;
        break;
    case SDL_EVENT_MOUSE_WHEEL:
        move = event.wheel.y > 0 ? -1 : event.wheel.y < 0 ? 1 : 0;
        break;
    case SDL_EVENT_KEY_UP:
    case SDL_EVENT_GAMEPAD_BUTTON_UP:
    case SDL_EVENT_MOUSE_BUTTON_UP:
        return true;
    default:
        return false;
    }
    if (message_active) {
        const bool two = (message_buttons >= 0 ? message_buttons
                          : SaveMessageFor(save_kind, message_code, message_value, message_text).buttons) % 2 == 1;
        if (two && move) message_focus = move < 0 ? 0 : 1;
        for (int b = 0; b < 2 && (moved || click); ++b) {
            if (save_button_rects[b].GetWidth() > 0 && save_button_rects[b].Contains(save_mouse)) {
                message_focus = b;
                finish = click ? 1 : finish;
            }
        }
        if (finish) {
            message_result = !two || (finish == 1 && message_focus == 1) ? 1 : 2;
            message_active = false;
            FinishSaveDialog();
        }
        return true;
    }
    const int count = int(save_rows.size());
    if (move && count) {
        choice_index = (choice_index + move + count) % count;
    }
    for (int i = 0; i < int(save_row_rects.size()) && (moved || click); ++i) {
        if (save_row_rects[i].GetWidth() > 0 && save_row_rects[i].Contains(save_mouse)) {
            choice_index = i;
            finish = click ? 1 : finish;
        }
    }
    if (finish) {
        choice_result = finish == 1 && count ? choice_index : -2;
        choice_active = false;
        FinishSaveDialog();
    }
    return true;
}

bool HandleEvent(const SDL_Event& event) {
    std::scoped_lock lock{imgui_mutex};
    if (!initialized) {
        return false;
    }
    if ((choice_active || message_active) && !menu_open) {
        return HandleSaveEvent(event);
    }
    ImGuiIO& io = ImGui::GetIO();
    const bool is_open = menu_open;
    switch (event.type) {
    case SDL_EVENT_KEY_DOWN:
    case SDL_EVENT_KEY_UP: {
        const bool down = event.type == SDL_EVENT_KEY_DOWN;
        static const bool capture_key = [] {
            const char* env = std::getenv("TLG_FRAME_CAPTURE_KEY");
            return env && *env == '1';
        }();
        if (down && !event.key.repeat && capture_key && event.key.key == SDLK_F11) {
            Vulkan::FrameCapture::Request();
            return true;
        }
        // tlg: F10 shows or hides the performance overlay (FPS counter) at any time.
        if (down && !event.key.repeat && event.key.key == SDLK_F10) {
            auto& settings = TlgSettings::Get();
            settings.show_fps = !settings.show_fps;
            return true;
        }
        if (down && !event.key.repeat &&
            (event.key.key == SDLK_INSERT || (is_open && event.key.key == SDLK_ESCAPE))) {
            SetOpen(event.key.key == SDLK_INSERT ? !is_open : false);
            return true;
        }
        if (!is_open) {
            return false;
        }
        io.AddKeyEvent(ImGuiMod_Ctrl, (event.key.mod & SDL_KMOD_CTRL) != 0);
        io.AddKeyEvent(ImGuiMod_Shift, (event.key.mod & SDL_KMOD_SHIFT) != 0);
        io.AddKeyEvent(ImGuiMod_Alt, (event.key.mod & SDL_KMOD_ALT) != 0);
        if (const ImGuiKey key = KeyFromSdl(event.key.key); key != ImGuiKey_None) {
            io.AddKeyEvent(key, down);
        }
        return true;
    }
    case SDL_EVENT_GAMEPAD_BUTTON_DOWN:
    case SDL_EVENT_GAMEPAD_BUTTON_UP: {
        const bool down = event.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN;
        const u8 button = event.gbutton.button;
        // R3+L2 opens the menu: L3+R3 is a game action in God of War III.
        if (button == SDL_GAMEPAD_BUTTON_RIGHT_STICK) {
            r3_down = down;
            if (down && l2_down) {
                SetOpen(!is_open);
                return true;
            }
        }
        if (!is_open) {
            return false;
        }
        if (const ImGuiKey key = KeyFromGamepad(button); key != ImGuiKey_None) {
            io.AddKeyEvent(key, down);
        }
        return true;
    }
    case SDL_EVENT_GAMEPAD_AXIS_MOTION: {
        if (event.gaxis.axis == SDL_GAMEPAD_AXIS_LEFT_TRIGGER) {
            const bool down = event.gaxis.value > 16000;
            if (down && !l2_down && r3_down) {
                l2_down = true;
                SetOpen(!is_open);
                return true;
            }
            l2_down = down;
        }
        return false;
    }
    case SDL_EVENT_TEXT_INPUT: {
        // Typed characters (Ctrl+click on a slider, a text field): key events alone erase but
        // do not type. SDL sends them while text input is on (UpdateTextInput).
        if (!is_open) {
            return false;
        }
        io.AddInputCharactersUTF8(event.text.text);
        return true;
    }
    case SDL_EVENT_MOUSE_MOTION: {
        if (!is_open) {
            return false;
        }
        const float density = PixelDensity(event.motion.windowID);
        io.AddMousePosEvent(event.motion.x * density, event.motion.y * density);
        return true;
    }
    case SDL_EVENT_MOUSE_BUTTON_DOWN:
    case SDL_EVENT_MOUSE_BUTTON_UP: {
        if (!is_open) {
            return false;
        }
        const int button = event.button.button == SDL_BUTTON_LEFT    ? 0
                           : event.button.button == SDL_BUTTON_RIGHT  ? 1
                           : event.button.button == SDL_BUTTON_MIDDLE ? 2
                                                                      : -1;
        if (button >= 0) {
            io.AddMouseButtonEvent(button, event.type == SDL_EVENT_MOUSE_BUTTON_DOWN);
        }
        return true;
    }
    case SDL_EVENT_MOUSE_WHEEL:
        if (!is_open) {
            return false;
        }
        io.AddMouseWheelEvent(event.wheel.x, event.wheel.y);
        return true;
    default:
        return false;
    }
}

// After "Apply and restart", the new options are kept once the game has shown about ten
// seconds of frames after loading (run.py restores the previous ones otherwise).
void ConfirmRestart() {
    static u32 frames = 0;
    auto& s = TlgSettings::Get();
    if (!s.restart_unconfirmed || loading || ++frames < 600) {
        return;
    }
    s.restart_unconfirmed = false;
    TlgSettings::Save();
    std::puts("Settings: graphics options confirmed after restart");
}

void SetBackgroundLoading(u32 done, u32 total) {
    background_done = done;
    background_total = total;
}

void SetLoading(bool active, u32 done, u32 total) {
    loading_done = done;
    loading_total = total;
    loading = active;
}

void Notice(const std::string& text, float seconds) {
    std::scoped_lock lock{imgui_mutex};
    notice_text = text;
    notice_until = std::chrono::steady_clock::now() +
                   std::chrono::milliseconds(static_cast<int>(seconds * 1000.0f));
}

static bool NoticeActive() {
    return std::chrono::steady_clock::now() < notice_until;
}

bool Visible() {
    const auto& s = TlgSettings::Get();
    const auto now = std::chrono::steady_clock::now();
    return initialized && (loading || background_total || menu_open || text_entry_active || choice_active ||
                           message_active || progress_on || now < progress_until || now < toast_until ||
                           NoticeActive() ||
                           choice_retiring || s.show_fps);
}

bool CapturesInput() {
    return menu_open || text_entry_active || choice_active || message_active;
}

void BeginSaveList(int kind, std::vector<SaveRow> rows, std::vector<TlgPng::Image> pictures, int focus) {
    std::scoped_lock lock{imgui_mutex};
    RetireChoiceTextures();
    choice_pictures = std::move(pictures);
    choice_pictures.resize(rows.size());
    save_kind = kind;
    save_rows = std::move(rows);
    save_row_rects.clear();
    choice_index = focus >= 0 && focus < int(save_rows.size()) ? focus : 0;
    choice_first = 0;
    choice_result = -1;
    message_active = false;
    progress_on = false;
    choice_active = true;
    ImGui::GetIO().MouseDrawCursor = true;
}

int PollSaveList() {
    return choice_result;
}

void BeginSaveMessage(int kind, int code, u64 value, const std::string& text, int buttons,
                      const SaveRow* entry, TlgPng::Image picture) {
    std::scoped_lock lock{imgui_mutex};
    RetireChoiceTextures();
    message_has_entry = entry != nullptr;
    if (entry) {
        message_entry = *entry;
        choice_pictures.clear();
        choice_pictures.push_back(std::move(picture));
    }
    save_kind = kind;
    message_code = code;
    message_value = value;
    message_text = text;
    message_buttons = buttons;
    // Deleting starts on "No"; everything else on the answer the player came for.
    message_focus = kind == 3 ? 0 : 1;
    save_button_rects[0] = save_button_rects[1] = ImRect();
    message_result = -1;
    choice_active = false;
    progress_on = false;
    message_active = true;
    ImGui::GetIO().MouseDrawCursor = true;
}

int PollSaveMessage() {
    return message_result;
}

void CloseSaveDialog() {
    std::scoped_lock lock{imgui_mutex};
    if (choice_active.exchange(false)) {
        choice_result = -2;
    }
    if (message_active.exchange(false)) {
        message_result = 2;
    }
    FinishSaveDialog();
}

void SaveProgress(int kind, int active, int percent, const char* text) {
    std::scoped_lock lock{imgui_mutex};
    const auto now = SaveClock::now();
    if (!active) {
        progress_on = false;
        return;
    }
    if (!progress_on && now >= progress_until) {
        progress_since = now;
    }
    progress_kind = kind;
    progress_percent = percent;
    if (text) {
        progress_text = text;
    }
    if (active == 2) {
        progress_until = now + std::chrono::milliseconds(1200);
    } else {
        progress_on = true;
    }
}

void SaveToast(int kind) {
    std::scoped_lock lock{imgui_mutex};
    const auto now = SaveClock::now();
    // A dialog's "saved" and the save's own unmount come together: one toast.
    if (now < toast_until + std::chrono::seconds(3)) {
        toast_until = std::max(toast_until, now + std::chrono::milliseconds(2600));
        return;
    }
    toast_kind = kind;
    toast_since = now;
    toast_until = now + std::chrono::milliseconds(2600);
}

void SetTextEntry(bool active, const std::string& prompt, const std::string& text) {
    std::scoped_lock lock{imgui_mutex};
    text_entry_active = active;
    text_entry_prompt = prompt;
    text_entry_text = text;
}

void Render(vk::CommandBuffer cmdbuf, vk::ImageView view, vk::Extent2D extent) {
    // Present interval for the FPS readout (measured also while nothing is drawn).
    const auto now = std::chrono::steady_clock::now();
    const float ms = std::chrono::duration<float, std::milli>(now - last_present).count();
    last_present = now;
    if (ms > 0.0f && ms < 1000.0f) {
        frame_ms_avg = frame_ms_avg == 0.0f ? ms : frame_ms_avg * 0.95f + ms * 0.05f;
    }
    ConfirmRestart();
    if (!Visible()) {
        return;
    }
    std::scoped_lock lock{imgui_mutex};
    ImGuiIO& io = ImGui::GetIO();
    io.DisplaySize = ImVec2(float(extent.width), float(extent.height));
    io.DeltaTime = ms > 0.0f && ms < 1000.0f ? ms / 1000.0f : 1.0f / 60.0f;
    // UI scale follows the display height (1080p = 1).
    const float scale = std::max(float(extent.height) / 1080.0f, 0.75f);
    if (std::abs(scale - base_scale) > 0.01f) {
        ImGuiStyle& style = ImGui::GetStyle();
        style.ScaleAllSizes(scale / base_scale);
        style.FontScaleMain = scale;
        base_scale = scale;
    }

    UpdateChoiceTextures();
    ImGui_ImplVulkan_NewFrame();
    ImGui::NewFrame();
    if (loading) {
        LoadingScreen();
    }
    if (menu_open) {
        Menu();
    }
    if (TlgSettings::Get().show_fps && !menu_open) {
        FpsCounter();
    }
    if (background_total && !loading && !menu_open) {
        BackgroundLoading();
    }
    if (text_entry_active) {
        TextEntryBox();
    }
    if (!menu_open) {
        SaveDialogs();
    }
    if (NoticeActive() && !menu_open) {
        NoticeBox();
    }
    ImGui::Render();

    const vk::RenderingAttachmentInfo attachment{
        .imageView = view,
        .imageLayout = vk::ImageLayout::eColorAttachmentOptimal,
        .loadOp = vk::AttachmentLoadOp::eLoad,
        .storeOp = vk::AttachmentStoreOp::eStore,
    };
    cmdbuf.beginRendering(vk::RenderingInfo{
        .renderArea = {{0, 0}, extent},
        .layerCount = 1,
        .colorAttachmentCount = 1,
        .pColorAttachments = &attachment,
    });
    {
        // Font atlas uploads submit to the graphics queue themselves.
        std::scoped_lock submit_lock{Vulkan::Scheduler::submit_mutex};
        ImGui_ImplVulkan_RenderDrawData(ImGui::GetDrawData(), cmdbuf);
    }
    cmdbuf.endRendering();
}

} // namespace TlgOverlay
