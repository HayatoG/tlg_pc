/* libScePad on SDL3 gamepads, with keyboard and mouse. SDL events are pumped by the window
 * thread (gpu/shim/window.cpp); here state is only sampled.
 *
 * Default keyboard layout (TLG_KEY_MAP or tlg.ini key_map changes the buttons, see
 * apply_button_map):
 *   WASD left stick, arrow keys right stick, Space Cross (jump), LShift Circle, E Square,
 *   Q Triangle (grab), 1 L1, 3 R1 (call Trico), R L2, F R2, Z L3, C R3,
 *   Enter Options, Tab left touchpad (photo mode), Backspace right touchpad (pause menu),
 *   IJKL d-pad (I up, K down, J left, L right).
 *   T / G tilt and Y shakes the simulated motion sensor (sample_motion); Tab + arrows swipes
 *   the touchpad (apply_swipe).
 * Mouse (while the window has it, see tlggpu_mouse_take; Esc releases it, a click takes it back):
 *   motion turns the camera (right stick, src/mouse_stick.h), left button Triangle (grab and
 *   hold on), right button R1 (call Trico), middle button Square. X1/X2 and the wheel are free
 *   for TLG_KEY_MAP ("Mouse X1", "Wheel Up", ...). */
#define _GNU_SOURCE
#include "runtime.h"
#include "gpu/tlggpu.h"
#include "mouse_stick.h"
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
#include <pthread.h>
#include <time.h>
#include <SDL3/SDL.h>
#include <sys/stat.h>

#define ERR_INVALID_ARG ((int32_t)0x80920001)
#define ERR_INVALID_HANDLE ((int32_t)0x80920003)
#define ERR_ALREADY_OPENED ((int32_t)0x80920004)
#define ERR_NOT_INITIALIZED ((int32_t)0x80920005)
#define PAD_HANDLE 1

enum {
    BTN_L3=0x2, BTN_R3=0x4, BTN_OPTIONS=0x8, BTN_UP=0x10, BTN_RIGHT=0x20, BTN_DOWN=0x40, BTN_LEFT=0x80,
    BTN_L2=0x100, BTN_R2=0x200, BTN_L1=0x400, BTN_R1=0x800, BTN_TRIANGLE=0x1000, BTN_CIRCLE=0x2000,
    BTN_CROSS=0x4000, BTN_SQUARE=0x8000, BTN_TOUCHPAD=0x100000,
    /* Host-only sources, never shown to the game: a click on one side of the touchpad from a
     * button or key without a touch surface (play_click turns them into a touch and a click). */
    CLICK_LEFT=0x40000000, CLICK_RIGHT=0x80000000,
};
typedef struct { uint16_t x, y; uint8_t id, reserve[3]; } PadTouch;
typedef struct {
    uint32_t buttons;
    uint8_t left_x, left_y, right_x, right_y;
    uint8_t l2, r2, analog_padding[2];
    float orientation[4], acceleration[3], angular_velocity[3];
    uint8_t touch_count, touch_reserve[3];
    uint32_t touch_held_time;
    PadTouch touches[2];
    uint8_t connected, pad0[3];
    uint64_t timestamp;
    uint8_t extension[16];
    uint8_t connected_count, reserve[2], unique_length, unique[12];
} PadData;
typedef struct {
    float pixel_density; uint16_t resolution_x, resolution_y;
    uint8_t dead_zone_left, dead_zone_right, connection_type, connected_count;
    uint8_t connected, pad[3];
    int32_t device_class;
    uint8_t reserve[8];
} ControllerInfo;
_Static_assert(sizeof(PadData)==120,"OrbisPadData layout");
_Static_assert(sizeof(PadTouch)==8,"OrbisPadTouch layout");
_Static_assert(__builtin_offsetof(PadData,touches)==60,"OrbisPadData touch offset");
_Static_assert(__builtin_offsetof(PadData,timestamp)==80,"OrbisPadData timestamp offset");
_Static_assert(sizeof(ControllerInfo)==28,"OrbisPadControllerInformation layout");

static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static int initialized, opened, sdl_ready;
static SDL_Gamepad *gamepad;
static size_t reads;
static uint8_t connected_count;

static uint64_t now_us(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return (uint64_t)t.tv_sec*1000000u+(uint64_t)t.tv_nsec/1000u; }
/* TLG_STICK_DEADZONE (0..0.5, default 0.10): stick values inside it read as centered, the rest
 * is rescaled, so worn sticks (drift) don't move the character or camera. */
static float stick_deadzone(void) {
    static float zone=-1;
    if (zone<0) { const char *e=getenv("TLG_STICK_DEADZONE"); zone=e && *e ? (float)atof(e) : 0.10f; if (zone<0) zone=0; if (zone>0.5f) zone=0.5f; }
    return zone;
}
static uint8_t to_byte(float f) {
    if (f>1.f) f=1.f;
    if (f<-1.f) f=-1.f;
    int x=(int)lroundf(f*127.5f+127.5f);
    return (uint8_t)(x<0 ? 0 : x>255 ? 255 : x);
}
static void stick_pair(int16_t vx, int16_t vy, uint8_t *ox, uint8_t *oy) {
    float fx=(float)vx/32767.f, fy=(float)vy/32767.f, zone=stick_deadzone();
    float mag=hypotf(fx,fy);
    if (mag<=zone) {
        *ox=*oy=128;
        return;
    }
    float scale=((mag>1.f ? 1.f : mag)-zone)/((1.f-zone)*mag);
    *ox=to_byte(fx*scale);
    *oy=to_byte(fy*scale);
}
static uint8_t trigger(int16_t v) { int x=v>>7; return (uint8_t)(x<0 ? 0 : x>255 ? 255 : x); }
static uint16_t touch_axis(float v, int max) {
    return (uint16_t)(v<=0.0f ? 0 : v>=1.0f ? max : (int)(v*max+0.5f));
}

/* A click without a touch surface (Back/View, Tab, Backspace, the pad file) is played like a
 * finger: the touch is reported CLICK_LEAD_US before the button, the button stays at least
 * CLICK_HOLD_US, and the touch lingers CLICK_TAIL_US after the release. God of War III opens
 * photo mode on the release of a left click with the finger still down, and ignores a touch
 * that comes and goes with the button. The side is chosen when the click starts and kept: the
 * right source with L1 held is a left click (photo mode on pads without a touchpad). */
enum { CLICK_LEAD_US=50000, CLICK_HOLD_US=50000, CLICK_TAIL_US=100000 };
static struct { int side; uint64_t pressed, released; } click={-1,0,0};
static void play_click(PadData *d) {
    const uint64_t now=d->timestamp;
    uint32_t sources=d->buttons & (CLICK_LEFT|CLICK_RIGHT);
    d->buttons&=~(CLICK_LEFT|CLICK_RIGHT);
    if ((d->buttons & BTN_TOUCHPAD) && !d->touch_count) { /* a replay, or a pad without fingers */
        d->buttons&=~BTN_TOUCHPAD;
        sources|=CLICK_LEFT;
    }
    const int side=(sources & CLICK_LEFT) ? 0 : (sources & CLICK_RIGHT) ? !(d->buttons & BTN_L1) : -1;
    if (side>=0 && (click.side<0 || click.released)) { click.side=side; click.pressed=now; click.released=0; }
    else if (side<0 && click.side>=0 && !click.released) click.released=now;
    if (click.side<0) return;
    const uint64_t down=click.pressed+CLICK_LEAD_US;
    uint64_t up=down+CLICK_HOLD_US;
    if (!click.released) up=UINT64_MAX;
    else if (click.released>up) up=click.released;
    if (now>=up && now-up>=CLICK_TAIL_US) { click.side=-1; return; }
    if (d->touch_count<2) {
        d->touches[d->touch_count]=(PadTouch){.x=click.side ? 1440 : 480,.y=471,.id=d->touch_count};
        ++d->touch_count;
    }
    if (now>=down && now<up) d->buttons|=BTN_TOUCHPAD;
}

/* Opens the first gamepad SDL knows about; called under lock. */
/* Every connected controller is open; the game reads the one used last (a press or a stick
 * past half way), so a second controller lying on the desk never takes over. */
#define MAX_GAMEPADS 8
static SDL_Gamepad *gamepads[MAX_GAMEPADS];
static int gamepad_active(SDL_Gamepad *g) {
    for (int b=0;b<SDL_GAMEPAD_BUTTON_COUNT;++b) if (SDL_GetGamepadButton(g,(SDL_GamepadButton)b)) return 1;
    for (int a=0;a<SDL_GAMEPAD_AXIS_COUNT;++a) if (abs(SDL_GetGamepadAxis(g,(SDL_GamepadAxis)a))>16000) return 1;
    return 0;
}
static SDL_Gamepad *current_gamepad(void) {
    static uint64_t last_scan;
    if (!sdl_ready) sdl_ready = SDL_WasInit(SDL_INIT_GAMEPAD) ? 1 : SDL_InitSubSystem(SDL_INIT_GAMEPAD) ? 1 : -1;
    if (sdl_ready<0) return NULL;
    for (int i=0;i<MAX_GAMEPADS;++i)
        if (gamepads[i] && !SDL_GamepadConnected(gamepads[i])) {
            if (gamepads[i]==gamepad) gamepad=NULL;
            SDL_CloseGamepad(gamepads[i]); gamepads[i]=NULL;
        }
    const uint64_t now=now_us();
    if (now-last_scan>1000000 || !gamepad) {
        last_scan=now;
        int count=0;
        SDL_JoystickID *ids=SDL_GetGamepads(&count);
        for (int c=0;ids && c<count;++c) {
            int open=0, slot=-1;
            for (int i=0;i<MAX_GAMEPADS;++i) {
                if (gamepads[i] && SDL_GetGamepadID(gamepads[i])==ids[c]) open=1;
                if (!gamepads[i] && slot<0) slot=i;
            }
            if (open || slot<0) continue;
            gamepads[slot]=SDL_OpenGamepad(ids[c]);
            if (gamepads[slot]) { ++connected_count; printf("Runtime: gamepad connected: %s\n",SDL_GetGamepadName(gamepads[slot])); }
        }
        SDL_free(ids);
    }
    for (int i=0;i<MAX_GAMEPADS;++i)
        if (gamepads[i] && gamepads[i]!=gamepad && (!gamepad || gamepad_active(gamepads[i]))) {
            if (gamepad) printf("Runtime: gamepad in use: %s\n",SDL_GetGamepadName(gamepads[i]));
            gamepad=gamepads[i];
            break;
        }
    return gamepad;
}
/* Button sources: a host button or key and the PS4 button it presses. The defaults below can be
 * changed per PS4 button with TLG_PAD_MAP (gamepad) and TLG_KEY_MAP (keyboard), e.g.
 * TLG_KEY_MAP="cross=Q,square=Left Shift" or TLG_PAD_MAP="cross=b,circle=a": comma-separated
 * <ps4 button>=<SDL key or gamepad button name>. A mapped PS4 button loses its default sources;
 * '|' gives it several ("triangle=Q|Mouse Left") and "none" leaves it without any. The keyboard
 * map also takes the mouse: Mouse Left/Middle/Right/X1/X2, Wheel Up/Down/Left/Right.
 * touchpad_left (alias touchpad) and touchpad_right are the two sides of the touchpad click:
 * photo mode and the pause menu. Back/View (Share on a DualSense) is the right click, and with
 * L1 held the left one. Sticks, triggers, the real touchpad click and the overlay shortcuts are
 * not remapped. */
static const struct { const char *name; uint32_t ps; } ps_names[]={
    {"cross",BTN_CROSS}, {"circle",BTN_CIRCLE}, {"square",BTN_SQUARE}, {"triangle",BTN_TRIANGLE},
    {"l1",BTN_L1}, {"r1",BTN_R1}, {"l2",BTN_L2}, {"r2",BTN_R2}, {"l3",BTN_L3}, {"r3",BTN_R3},
    {"options",BTN_OPTIONS}, {"touchpad",CLICK_LEFT}, {"touchpad_left",CLICK_LEFT}, {"touchpad_right",CLICK_RIGHT},
    {"up",BTN_UP}, {"down",BTN_DOWN}, {"left",BTN_LEFT}, {"right",BTN_RIGHT},
};
/* Mouse sources in the keyboard map: MOUSE_SOURCE + bit of TlgGpuMouse (SDL button - 1), then
 * the wheel directions (pulses, see sample_mouse). */
enum { MOUSE_SOURCE=0x10000, MOUSE_LEFT=MOUSE_SOURCE, MOUSE_MIDDLE, MOUSE_RIGHT, MOUSE_X1, MOUSE_X2,
       WHEEL_UP, WHEEL_DOWN, WHEEL_LEFT, WHEEL_RIGHT, MOUSE_SOURCE_END };
static const struct { const char *name; int source; } mouse_names[]={
    {"Mouse Left",MOUSE_LEFT}, {"Mouse Middle",MOUSE_MIDDLE}, {"Mouse Right",MOUSE_RIGHT},
    {"Mouse X1",MOUSE_X1}, {"Mouse X2",MOUSE_X2}, {"Wheel Up",WHEEL_UP}, {"Wheel Down",WHEEL_DOWN},
    {"Wheel Left",WHEEL_LEFT}, {"Wheel Right",WHEEL_RIGHT},
};
typedef struct { int source; uint32_t ps; } ButtonSource;
typedef struct { ButtonSource entries[48]; size_t count; } ButtonMap;
static ButtonMap pad_map={{
    {SDL_GAMEPAD_BUTTON_SOUTH,BTN_CROSS}, {SDL_GAMEPAD_BUTTON_EAST,BTN_CIRCLE},
    {SDL_GAMEPAD_BUTTON_WEST,BTN_SQUARE}, {SDL_GAMEPAD_BUTTON_NORTH,BTN_TRIANGLE},
    {SDL_GAMEPAD_BUTTON_LEFT_SHOULDER,BTN_L1}, {SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER,BTN_R1},
    {SDL_GAMEPAD_BUTTON_LEFT_STICK,BTN_L3}, {SDL_GAMEPAD_BUTTON_RIGHT_STICK,BTN_R3},
    {SDL_GAMEPAD_BUTTON_START,BTN_OPTIONS}, {SDL_GAMEPAD_BUTTON_BACK,CLICK_RIGHT},
    {SDL_GAMEPAD_BUTTON_TOUCHPAD,BTN_TOUCHPAD},
    {SDL_GAMEPAD_BUTTON_DPAD_UP,BTN_UP}, {SDL_GAMEPAD_BUTTON_DPAD_DOWN,BTN_DOWN},
    {SDL_GAMEPAD_BUTTON_DPAD_LEFT,BTN_LEFT}, {SDL_GAMEPAD_BUTTON_DPAD_RIGHT,BTN_RIGHT},
},15};
static ButtonMap key_map={{
    {SDL_SCANCODE_SPACE,BTN_CROSS}, {SDL_SCANCODE_LSHIFT,BTN_CIRCLE}, {SDL_SCANCODE_E,BTN_SQUARE},
    {SDL_SCANCODE_Q,BTN_TRIANGLE}, {SDL_SCANCODE_1,BTN_L1}, {SDL_SCANCODE_3,BTN_R1},
    {SDL_SCANCODE_R,BTN_L2}, {SDL_SCANCODE_F,BTN_R2}, {SDL_SCANCODE_Z,BTN_L3}, {SDL_SCANCODE_C,BTN_R3},
    {SDL_SCANCODE_RETURN,BTN_OPTIONS}, {SDL_SCANCODE_TAB,CLICK_LEFT}, {SDL_SCANCODE_BACKSPACE,CLICK_RIGHT},
    {SDL_SCANCODE_I,BTN_UP}, {SDL_SCANCODE_K,BTN_DOWN}, {SDL_SCANCODE_J,BTN_LEFT}, {SDL_SCANCODE_L,BTN_RIGHT},
    {MOUSE_LEFT,BTN_TRIANGLE}, {MOUSE_RIGHT,BTN_R1}, {MOUSE_MIDDLE,BTN_SQUARE},
},20};

static char *trim(char *text) {
    while (*text==' ' || *text=='\t') ++text;
    char *end=text+strlen(text);
    while (end>text && (end[-1]==' ' || end[-1]=='\t' || end[-1]=='\r' || end[-1]=='\n')) *--end=0;
    return text;
}

/* A source name: a key (or mouse button) for the keyboard map, a gamepad button otherwise; -1
 * when the name is unknown. */
static int source_from_name(const char *name, bool keyboard) {
    if (!keyboard) {
        const SDL_GamepadButton b=SDL_GetGamepadButtonFromString(name);
        return b>SDL_GAMEPAD_BUTTON_INVALID ? (int)b : -1;
    }
    for (size_t i=0;i<sizeof(mouse_names)/sizeof(*mouse_names);++i) if (!SDL_strcasecmp(name,mouse_names[i].name)) return mouse_names[i].source;
    const SDL_Scancode k=SDL_GetScancodeFromName(name);
    return k>SDL_SCANCODE_UNKNOWN ? (int)k : -1;
}

/* Applies a TLG_PAD_MAP/TLG_KEY_MAP value; returns how many entries were used. Bad entries are
 * logged and skipped, so their PS4 button keeps its default. */
static int apply_button_map(ButtonMap *map, const char *spec, bool keyboard) {
    if (!spec || !*spec) return 0;
    char copy[1024];
    snprintf(copy,sizeof(copy),"%s",spec);
    int used=0;
    char *entry=copy;
    while (entry) {
        char *next=strchr(entry,',');
        if (next) *next++=0;
        char *eq=strchr(entry,'=');
        if (!eq) {
            if (*trim(entry)) printf("Runtime: pad map: ignored '%s' (expected button=name)\n",trim(entry));
            entry=next;
            continue;
        }
        *eq=0;
        char *button=trim(entry), *names=trim(eq+1);
        entry=next;
        uint32_t ps=0;
        for (size_t i=0;i<sizeof(ps_names)/sizeof(*ps_names);++i) if (!SDL_strcasecmp(button,ps_names[i].name)) ps=ps_names[i].ps;
        const bool none=!SDL_strcasecmp(names,"none");
        int sources[8], count=0;
        for (char *name=names, *bar; name && !none; name=bar) {
            if ((bar=strchr(name,'|'))) *bar++=0;
            const int source=*trim(name) ? source_from_name(trim(name),keyboard) : -1;
            if (source<0) { if (*trim(name)) printf("Runtime: pad map: unknown name '%s'\n",trim(name)); }
            else if (count<8) sources[count++]=source;
        }
        if (!ps || (!count && !none)) {
            printf("Runtime: pad map: ignored '%s=%s'\n",button,names);
            continue;
        }
        size_t kept=0;
        for (size_t i=0;i<map->count;++i) if (map->entries[i].ps!=ps) map->entries[kept++]=map->entries[i];
        map->count=kept;
        for (int i=0;i<count;++i)
            if (map->count<sizeof(map->entries)/sizeof(*map->entries)) map->entries[map->count++]=(ButtonSource){sources[i],ps};
        ++used;
    }
    return used;
}

static void load_button_maps(void) {
    static bool loaded;
    if (loaded) return;
    loaded=true;
    const int pad=apply_button_map(&pad_map,getenv("TLG_PAD_MAP"),false);
    /* TLG_KEY_MAP wins over tlg.ini's key_map (the launcher's Controls). */
    const char *env=getenv("TLG_KEY_MAP");
    TlgGpuInputSettings in;
    tlggpu_input_settings(&in);
    const int keys=apply_button_map(&key_map,env && *env ? env : in.key_map,true);
    if (pad || keys) printf("Runtime: pad map: %d gamepad and %d keyboard buttons remapped\n",pad,keys);
}

/* Motion (orientation quaternion, acceleration in g, angular velocity in rad/s; axes as SDL's:
 * x right, y up, z toward the player). A controller with sensors (DualShock 4, DualSense, Switch
 * Pro...) reports its gyro/accelerometer through SDL; the orientation integrates the gyro and
 * leans on gravity. Without sensors the tilt is simulated, so motion prompts can be passed with
 * any controller or the keyboard:
 *   keyboard: T / G hold the controller turned sideways (to one side / the other), Y shakes it;
 *   gamepad: "sensor mode", toggled by a tap on TLG_MOTION_BUTTON (default "misc1": Share/Capture;
 *   any SDL button name) or on L3+R3 together. While it is on, the left stick tilts the controller
 *   and the bottom face button (cross / A / Nintendo B) shakes it; both are hidden from the game,
 *   so the character neither walks nor jumps. A notice on screen tells the mode.
 * TLG_MOTION=off disables real sensors (simulation still works). */
static int injected_motion; /* TLG_PAD_FILE tokens: 1 tilt_right (T), 2 tilt_left (G), 4 shake (Y) */
typedef struct { float w, x, y, z; } Quat;
static struct { Quat q; float roll, pitch; uint64_t last_us; int sensors, warned, mode, toggle_held; } motion={{1,0,0,0},0,0,0,-1,0,0,0};
static Quat quat_mul(Quat a, Quat b) {
    return (Quat){a.w*b.w-a.x*b.x-a.y*b.y-a.z*b.z, a.w*b.x+a.x*b.w+a.y*b.z-a.z*b.y,
                  a.w*b.y-a.x*b.z+a.y*b.w+a.z*b.x, a.w*b.z+a.x*b.y-a.y*b.x+a.z*b.w};
}
static Quat quat_norm(Quat q) {
    float n=sqrtf(q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z);
    return n>0 ? (Quat){q.w/n,q.x/n,q.y/n,q.z/n} : (Quat){1,0,0,0};
}
/* Gravity as seen by the controller for orientation q: rotate world up (0,1,0) by q^-1. */
static void gravity_of(Quat q, float out[3]) {
    Quat c={q.w,-q.x,-q.y,-q.z}, v={0,0,1,0};
    Quat r=quat_mul(quat_mul(c,v),q);
    out[0]=r.x; out[1]=r.y; out[2]=r.z;
}
static int motion_button(void) {
    static int button=-2;
    if (button==-2) {
        const char *name=getenv("TLG_MOTION_BUTTON");
        button=(int)SDL_GetGamepadButtonFromString(name && *name ? name : "misc1");
    }
    return button;
}
static void sample_motion(PadData *d, SDL_Gamepad *g, const bool *k) {
    const uint64_t now=now_us();
    float dt=motion.last_us ? (float)(now-motion.last_us)*1e-6f : 0.f;
    if (dt>0.1f) dt=0.1f;
    motion.last_us=now;
    if (motion.sensors<0) { const char *e=getenv("TLG_MOTION"); motion.sensors=!(e && !strcmp(e,"off")); }
    /* Real sensors. */
    float gyro[3]={0,0,0}, accel[3]={0,0,0};
    int real=0;
    if (g && motion.sensors && SDL_GamepadHasSensor(g,SDL_SENSOR_GYRO) && SDL_GamepadHasSensor(g,SDL_SENSOR_ACCEL)) {
        if (!SDL_GamepadSensorEnabled(g,SDL_SENSOR_GYRO)) {
            SDL_SetGamepadSensorEnabled(g,SDL_SENSOR_GYRO,true);
            SDL_SetGamepadSensorEnabled(g,SDL_SENSOR_ACCEL,true);
            printf("Runtime: motion sensors enabled on %s\n",SDL_GetGamepadName(g));
        }
        real=SDL_GetGamepadSensorData(g,SDL_SENSOR_GYRO,gyro,3) && SDL_GetGamepadSensorData(g,SDL_SENSOR_ACCEL,accel,3);
    }
    /* Simulated tilt: target roll/pitch from keys or the modifier + right stick. */
    float roll=0, pitch=0;
    int shake=0, simulated=0;
    if ((k && k[SDL_SCANCODE_T]) || (injected_motion & 1)) { roll=1.5708f; simulated=1; }
    if ((k && k[SDL_SCANCODE_G]) || (injected_motion & 2)) { roll=-1.5708f; simulated=1; }
    if ((k && k[SDL_SCANCODE_Y]) || (injected_motion & 4)) { shake=1; simulated=1; }
    if (g) {
        const int sticks=SDL_GetGamepadButton(g,SDL_GAMEPAD_BUTTON_LEFT_STICK) && SDL_GetGamepadButton(g,SDL_GAMEPAD_BUTTON_RIGHT_STICK);
        const int toggle=sticks || (motion_button()>=0 && SDL_GetGamepadButton(g,(SDL_GamepadButton)motion_button()));
        if (toggle && !motion.toggle_held) {
            motion.mode=!motion.mode;
            const char *lang=getenv("TLG_UI_LANG");
            const int pt=!(lang && !strncmp(lang,"en",2));
            tlggpu_overlay_notice(motion.mode ? (pt ? "Modo sensor LIGADO: analógico esquerdo inclina, X/A sacode"
                                                    : "Sensor mode ON: left stick tilts, cross/A shakes")
                                              : (pt ? "Modo sensor desligado" : "Sensor mode off"), 3.0f);
            printf("Runtime: sensor mode %s\n",motion.mode ? "on" : "off");
        }
        motion.toggle_held=toggle;
        if (sticks) d->buttons&=~(uint32_t)(BTN_L3|BTN_R3);
        if (motion.mode) {
            roll=(float)SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_LEFTX)/32767.f*1.5708f;
            pitch=(float)SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_LEFTY)/32767.f*1.5708f;
            if (SDL_GetGamepadButton(g,SDL_GAMEPAD_BUTTON_SOUTH)) shake=1;
            d->buttons&=~(uint32_t)BTN_CROSS;
            d->left_x=d->left_y=128;
            simulated=1;
        }
    }
    if (real && !simulated) {
        /* Integrate the gyro, then pull slowly toward the measured gravity (complementary filter). */
        Quat w={0,gyro[0]*dt*0.5f,gyro[1]*dt*0.5f,gyro[2]*dt*0.5f};
        const Quat dq=quat_mul(motion.q,w);
        motion.q=quat_norm((Quat){motion.q.w+dq.w,motion.q.x+dq.x,motion.q.y+dq.y,motion.q.z+dq.z});
        float a[3]={accel[0]/9.80665f,accel[1]/9.80665f,accel[2]/9.80665f}, e[3];
        gravity_of(motion.q,e);
        float n=sqrtf(a[0]*a[0]+a[1]*a[1]+a[2]*a[2]);
        if (n>0.5f && n<1.5f) { /* error axis = measured x estimated, applied as a small rotation */
            float c[3]={a[1]*e[2]-a[2]*e[1],a[2]*e[0]-a[0]*e[2],a[0]*e[1]-a[1]*e[0]}, gain=0.02f;
            Quat fix={1,c[0]*gain/n,c[1]*gain/n,c[2]*gain/n};
            motion.q=quat_norm(quat_mul(motion.q,fix));
        }
        for (int i=0;i<3;++i) { d->acceleration[i]=a[i]; d->angular_velocity[i]=gyro[i]; }
    } else {
        /* Ease toward the target so the game sees a turning motion, not a jump. */
        const float rate=dt>0 ? 1.f-expf(-dt*12.f) : 1.f;
        float old_roll=motion.roll, old_pitch=motion.pitch;
        motion.roll+=(roll-motion.roll)*rate; motion.pitch+=(pitch-motion.pitch)*rate;
        Quat qr={cosf(motion.roll*0.5f),0,0,sinf(-motion.roll*0.5f)};  /* roll about z (toward player) */
        Quat qp={cosf(motion.pitch*0.5f),sinf(motion.pitch*0.5f),0,0}; /* pitch about x */
        motion.q=quat_norm(quat_mul(qp,qr));
        float gv[3]; gravity_of(motion.q,gv);
        for (int i=0;i<3;++i) d->acceleration[i]=gv[i];
        if (dt>0) { d->angular_velocity[0]=(motion.pitch-old_pitch)/dt; d->angular_velocity[2]=-(motion.roll-old_roll)/dt; }
        if (shake) { /* ~7 Hz up/down shake of +-2.5 g */
            const float t=(float)(now%1000000u)*1e-6f, s=sinf(t*6.2831853f*7.f);
            d->acceleration[1]+=2.5f*s; d->angular_velocity[0]+=6.f*cosf(t*6.2831853f*7.f);
        }
        if (simulated && !motion.warned) { motion.warned=1; puts("Runtime: simulated controller tilt/shake in use"); }
    }
    d->orientation[0]=motion.q.x; d->orientation[1]=motion.q.y; d->orientation[2]=motion.q.z; d->orientation[3]=motion.q.w;
}
/* Touchpad swipes for controllers without a touchpad ("Open Door": swipe right): hold View/
 * Select/- (gamepad) or Tab (keyboard) and push the right stick (arrow keys): a finger moves
 * from the middle of the pad toward that side. A quick tap without moving still clicks. */
static struct { int active; } swipe;
static void apply_swipe(PadData *d, SDL_Gamepad *g, const bool *k) {
    float x=0, y=0;
    int held=0;
    if (g && SDL_GetGamepadButton(g,SDL_GAMEPAD_BUTTON_BACK)) {
        held=1;
        x=(float)SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_RIGHTX)/32767.f;
        y=(float)SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_RIGHTY)/32767.f;
    }
    if (k && k[SDL_SCANCODE_TAB]) {
        held=1;
        if (k[SDL_SCANCODE_LEFT]) x=-1;
        if (k[SDL_SCANCODE_RIGHT]) x=1;
        if (k[SDL_SCANCODE_UP]) y=-1;
        if (k[SDL_SCANCODE_DOWN]) y=1;
    }
    if (!held) { swipe.active=0; return; }
    if (!swipe.active && x*x+y*y<0.09f) return; /* not moved yet: still a click */
    if (!swipe.active) { swipe.active=1; click.side=-1; }
    d->buttons&=~(uint32_t)(CLICK_LEFT|CLICK_RIGHT|BTN_TOUCHPAD);
    d->right_x=d->right_y=128;
    if (d->touch_count<2) {
        d->touches[d->touch_count]=(PadTouch){.x=touch_axis(0.5f+x*0.47f,1919),.y=touch_axis(0.5f+y*0.47f,942),
                                              .id=(uint8_t)(d->touch_count+8)};
        ++d->touch_count;
    }
}
/* The mouse: motion on the right stick, buttons and wheel pulses as source bits (1 << (source -
 * MOUSE_SOURCE)). A wheel notch holds its button WHEEL_PULSE_US, then WHEEL_GAP_US up, so each
 * notch is one press (menus scroll one item per notch). TLG_MOUSE_LOG=1 (or TLG_MOUSE_TEST)
 * logs what the game gets. Called under lock. */
enum { WHEEL_PULSE_US=80000, WHEEL_GAP_US=40000 };
static MouseStick mouse_stick;
static uint64_t mouse_last_us;
static struct { int pending; uint64_t until, next; } wheel[4];
static size_t mouse_samples;
static uint32_t sample_mouse(PadData *d) {
    TlgGpuMouse m;
    tlggpu_mouse_take(&m);
    TlgGpuInputSettings in;
    tlggpu_input_settings(&in);
    const uint64_t now=d->timestamp;
    const float dt=mouse_last_us ? (float)(now-mouse_last_us)/1e6f : MOUSE_STICK_WINDOW_S;
    mouse_last_us=now;
    static bool was_captured;
    if (!in.mouse_enabled || !m.captured) {
        memset(&mouse_stick,0,sizeof(mouse_stick));
        memset(wheel,0,sizeof(wheel));
        was_captured=false;
        return 0;
    }
    if (!was_captured) { m.dx=m.dy=0; was_captured=true; } /* motion from before the game read the pad */
    ++mouse_samples;
    const MouseStickParams p={in.sensitivity,in.smoothing,in.accel,in.deadzone,in.invert_y};
    mouse_stick_update(&mouse_stick,&p,m.dx,m.dy,dt);
    const uint8_t base_x=d->right_x, base_y=d->right_y;
    d->right_x=mouse_stick_add(d->right_x,mouse_stick_axis(&mouse_stick,&p,0));
    d->right_y=mouse_stick_add(d->right_y,mouse_stick_axis(&mouse_stick,&p,1));
    uint32_t bits=m.held|m.pressed;
    const int32_t notches[4]={m.wheel_up,m.wheel_down,m.wheel_left,m.wheel_right};
    for (int i=0;i<4;++i) {
        wheel[i].pending+=notches[i];
        if (wheel[i].pending>8) wheel[i].pending=8;
        if (now>=wheel[i].next && wheel[i].pending>0) {
            --wheel[i].pending;
            wheel[i].until=now+WHEEL_PULSE_US;
            wheel[i].next=wheel[i].until+WHEEL_GAP_US;
        }
        if (now<wheel[i].until) bits|=1u<<(WHEEL_UP-MOUSE_SOURCE+i);
    }
    static int log_state=-1; static uint64_t last_log;
    if (log_state<0) { const char *a=getenv("TLG_MOUSE_LOG"), *b=getenv("TLG_MOUSE_TEST"); log_state=(a && *a=='1') || (b && *b=='1'); }
    if (log_state) {
        static bool was_active;
        const bool active=bits || d->right_x!=base_x || d->right_y!=base_y;
        if ((active && now-last_log>=250000) || (was_active && !active)) {
            printf("Runtime: mouse dx=%.1f dy=%.1f -> right stick %u,%u, mouse buttons 0x%x\n",m.dx,m.dy,
                   d->right_x,d->right_y,bits);
            last_log=now;
        }
        was_active=active;
    }
    return bits;
}

static void key_axis(uint8_t *axis, bool negative, bool positive) {
    if (negative || positive) *axis=(uint8_t)(128-(negative ? 128 : 0)+(positive ? 127 : 0));
}
static void sample_host(PadData *d) {
    memset(d,0,sizeof(*d));
    d->left_x=d->left_y=d->right_x=d->right_y=128;
    d->orientation[3]=1.0f;
    d->connected=1; d->connected_count=connected_count ? connected_count : 1;
    d->timestamp=now_us();
    SDL_Gamepad *g=current_gamepad();
    if (tlggpu_overlay_captures_input()) return; /* settings menu open: neutral input */
    const bool *k=SDL_WasInit(SDL_INIT_VIDEO) ? SDL_GetKeyboardState(NULL) : NULL;
    load_button_maps();
    if (g) {
        for (size_t i=0;i<pad_map.count;++i)
            if (SDL_GetGamepadButton(g,(SDL_GamepadButton)pad_map.entries[i].source)) d->buttons|=pad_map.entries[i].ps;
        const uint32_t mapped=d->buttons;
        stick_pair(SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_LEFTX),SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_LEFTY),&d->left_x,&d->left_y);
        stick_pair(SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_RIGHTX),SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_RIGHTY),&d->right_x,&d->right_y);
        d->l2=trigger(SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_LEFT_TRIGGER)); d->r2=trigger(SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_RIGHT_TRIGGER));
        if (d->l2>30) d->buttons|=BTN_L2;
        if (d->r2>30) d->buttons|=BTN_R2;
        if (mapped & BTN_L2) d->l2=255;
        if (mapped & BTN_R2) d->r2=255;
        if (SDL_GetNumGamepadTouchpads(g)>0) {
            const int fingers=SDL_GetNumGamepadTouchpadFingers(g,0);
            for (int finger=0;finger<fingers && d->touch_count<2;++finger) {
                bool down=false;
                float x=0, y=0;
                if (SDL_GetGamepadTouchpadFinger(g,0,finger,&down,&x,&y,NULL) && down) {
                    d->touches[d->touch_count++]=(PadTouch){.x=touch_axis(x,1919),
                        .y=touch_axis(y,942),.id=(uint8_t)finger};
                }
            }
        }
    }
    sample_motion(d,g,k);
    /* The keyboard works with or without a gamepad: its buttons add to the pad's, and a stick
     * follows the keys only while one of them is held. */
    if (!k) return;
    key_axis(&d->left_x,k[SDL_SCANCODE_A],k[SDL_SCANCODE_D]);
    key_axis(&d->left_y,k[SDL_SCANCODE_W],k[SDL_SCANCODE_S]);
    key_axis(&d->right_x,k[SDL_SCANCODE_LEFT],k[SDL_SCANCODE_RIGHT]);
    key_axis(&d->right_y,k[SDL_SCANCODE_UP],k[SDL_SCANCODE_DOWN]);
    const uint32_t mouse=sample_mouse(d); /* adds to the right stick */
    for (size_t i=0;i<key_map.count;++i) {
        const int source=key_map.entries[i].source;
        const bool down=source>=MOUSE_SOURCE ? source<MOUSE_SOURCE_END && (mouse>>(source-MOUSE_SOURCE) & 1)
                                             : source<SDL_SCANCODE_COUNT && k[source];
        if (down) d->buttons|=key_map.entries[i].ps;
    }
    apply_swipe(d,g,k); /* after the key map: Tab+arrows swipe instead of clicking */
    if (d->buttons & BTN_L2) d->l2=255;
    if (d->buttons & BTN_R2) d->r2=255;
}

/* TLG_PAD_FILE=<file>: scripted input for automated runs. The file holds whitespace-separated
 * tokens, re-read when it changes: button names (cross circle square triangle l1 r1 l2 r2 l3 r3
 * options touchpad touchpad_left touchpad_right up down left right) are held while listed;
 * touchpad is the left side; lx= ly= rx= ry= (0..255) override the sticks; tilt_right, tilt_left
 * and shake drive the simulated motion sensor (see sample_motion). An empty file
 * releases everything. */
static struct { uint32_t buttons; int stick[4]; } injected={0,{-1,-1,-1,-1}};
static int replay_armed;      /* 1 while a TLG_PAD_REPLAY recording plays, 2 once it ended */
static uint64_t replay_start; /* 0: (re)start at the next sample */
static void read_inject(void) {
    static const char *path; static int checked; static uint64_t last_check; static struct timespec mtime;
    if (!checked) { path=getenv("TLG_PAD_FILE"); checked=1; }
    if (!path || !*path) return;
    uint64_t now=now_us();
    if (now-last_check<20000) return;
    last_check=now;
    struct stat st;
    if (stat(path,&st)!=0) return;
#ifdef _WIN32
    /* Whole-second mtimes: the size tells two edits within a second apart. */
    if (st.st_mtime==mtime.tv_sec && st.st_size==mtime.tv_nsec) return;
    mtime=(struct timespec){st.st_mtime,(long)st.st_size};
#else
    if (st.st_mtim.tv_sec==mtime.tv_sec && st.st_mtim.tv_nsec==mtime.tv_nsec) return;
    mtime=st.st_mtim;
#endif
    FILE *f=fopen(path,"r");
    if (!f) return;
    static const char *sticks[]={"lx=","ly=","rx=","ry="};
    injected.buttons=0;
    injected_motion=0;
    for (int i=0;i<4;++i) injected.stick[i]=-1;
    char token[64];
    while (fscanf(f,"%63s",token)==1) {
        if (!strcmp(token,"replay") && replay_armed!=1) { replay_armed=1; replay_start=0; } /* TLG_PAD_REPLAY */
        for (size_t i=0;i<sizeof(ps_names)/sizeof(*ps_names);++i) if (!strcmp(token,ps_names[i].name)) injected.buttons|=ps_names[i].ps;
        if (!strcmp(token,"tilt_right")) injected_motion|=1;
        if (!strcmp(token,"tilt_left")) injected_motion|=2;
        if (!strcmp(token,"shake")) injected_motion|=4;
        for (int i=0;i<4;++i) if (!strncmp(token,sticks[i],3)) { int v=atoi(token+3); injected.stick[i]=v<0 ? 0 : v>255 ? 255 : v; }
    }
    fclose(f);
    printf("Runtime: pad file: buttons 0x%x sticks %d %d %d %d\n",injected.buttons,
           injected.stick[0],injected.stick[1],injected.stick[2],injected.stick[3]);
}
/* TLG_PAD_RECORD=<file>: F9 starts and stops recording the pad state (gamepad or keyboard) with
 * the time since F9; TLG_PAD_REPLAY=<file> plays such a recording back, started by the token
 * "replay" in TLG_PAD_FILE (scripted tests repeat a route the player ran once). Lines: ms buttons
 * lx ly rx ry l2 r2, written when the state changes. */
typedef struct { uint32_t ms, buttons; uint8_t axes[4], l2, r2; } PadSample;
static FILE *record_file;
static uint64_t record_start;
static PadSample record_last;
static void record_sample(const PadData *d) {
    static const char *path; static int checked, f9_was_down;
    if (!checked) { path=getenv("TLG_PAD_RECORD"); checked=1; }
    if (!path || !*path || !sdl_ready) return;
    const bool *k=SDL_GetKeyboardState(NULL);
    const int f9=k && k[SDL_SCANCODE_F9];
    if (f9 && !f9_was_down) {
        if (record_file) {
            fclose(record_file); record_file=NULL;
            printf("Runtime: pad recording stopped (%s)\n",path);
        } else if ((record_file=fopen(path,"w"))) {
            record_start=now_us();
            memset(&record_last,0xff,sizeof(record_last));
            printf("Runtime: pad recording started (%s, F9 stops)\n",path);
        }
    }
    f9_was_down=f9;
    if (!record_file) return;
    PadSample s={(uint32_t)((now_us()-record_start)/1000),d->buttons,
                 {d->left_x,d->left_y,d->right_x,d->right_y},d->l2,d->r2};
    if (s.buttons==record_last.buttons && !memcmp(s.axes,record_last.axes,4) &&
        s.l2==record_last.l2 && s.r2==record_last.r2) return;
    record_last=s;
    fprintf(record_file,"%u %u %u %u %u %u %u %u\n",s.ms,s.buttons,s.axes[0],s.axes[1],s.axes[2],
            s.axes[3],s.l2,s.r2);
    fflush(record_file);
}
static PadSample *replay; static size_t replay_count, replay_next;
static void replay_sample(PadData *d) {
    if (!replay_armed) return;
    if (!replay_start) {
        static int loaded;
        if (!loaded) {
            loaded=1;
            const char *path=getenv("TLG_PAD_REPLAY");
            FILE *f=path ? fopen(path,"r") : NULL;
            PadSample s; unsigned v[8]; size_t cap=0;
            while (f && fscanf(f,"%u %u %u %u %u %u %u %u",&v[0],&v[1],&v[2],&v[3],&v[4],&v[5],&v[6],&v[7])==8) {
                s=(PadSample){v[0],v[1],{(uint8_t)v[2],(uint8_t)v[3],(uint8_t)v[4],(uint8_t)v[5]},(uint8_t)v[6],(uint8_t)v[7]};
                if (replay_count==cap && !(replay=realloc(replay,(cap=cap ? cap*2 : 1024)*sizeof(*replay)))) break;
                replay[replay_count++]=s;
            }
            if (f) fclose(f);
            printf("Runtime: pad replay of %zu samples from %s\n",replay_count,path ? path : "(unset)");
        }
        replay_start=now_us();
        replay_next=0;
    }
    const uint32_t ms=(uint32_t)((now_us()-replay_start)/1000);
    while (replay_next<replay_count && replay[replay_next].ms<=ms) ++replay_next;
    if (!replay_next) return;
    if (replay_next==replay_count && ms>replay[replay_count-1].ms+500) {
        if (replay_armed==1) { puts("Runtime: pad replay finished"); replay_armed=2; }
        return;
    }
    const PadSample *s=&replay[replay_next-1];
    d->buttons=s->buttons;
    d->left_x=s->axes[0]; d->left_y=s->axes[1]; d->right_x=s->axes[2]; d->right_y=s->axes[3];
    d->l2=s->l2; d->r2=s->r2;
}
/* After the menu or the text dialog closes, buttons still held (the Cross that accepted a
 * name) stay hidden until released: the game would take them as a new press. */
static int hold_after_capture;
static void sample(PadData *d) {
    sample_host(d);
    if (tlggpu_overlay_captures_input()) { hold_after_capture=1; click.side=-1; return; }
    record_sample(d); /* the click sources as they are: a replay plays them again */
    read_inject();
    replay_sample(d);
    d->buttons|=injected.buttons;
    if (injected.buttons & BTN_L2) d->l2=255;
    if (injected.buttons & BTN_R2) d->r2=255;
    uint8_t *axes[4]={&d->left_x,&d->left_y,&d->right_x,&d->right_y};
    for (int i=0;i<4;++i) if (injected.stick[i]>=0) *axes[i]=(uint8_t)injected.stick[i];
    play_click(d);
    if (hold_after_capture) {
        if (d->buttons) d->buttons=0;
        else hold_after_capture=0;
    }
}

static ABI int32_t pad_init(void) { pthread_mutex_lock(&lock); initialized=1; pthread_mutex_unlock(&lock); return 0; }
static ABI int32_t pad_open(int32_t user, int32_t type, int32_t index, const void *param) {
    (void)param;
    if (!initialized) return ERR_NOT_INITIALIZED;
    if (user!=1) return ERR_INVALID_ARG;
    if (type!=0 && type!=2) return ERR_INVALID_ARG; /* standard / special port */
    if (index) return ERR_INVALID_ARG;
    pthread_mutex_lock(&lock);
    int already=opened; opened=1;
    pthread_mutex_unlock(&lock);
    if (already) return ERR_ALREADY_OPENED;
    puts("Runtime: pad opened for user 1 (SDL gamepad or keyboard)");
    return PAD_HANDLE;
}
static ABI int32_t pad_close(int32_t handle) {
    if (handle!=PAD_HANDLE || !opened) return ERR_INVALID_HANDLE;
    opened=0; return 0;
}
static ABI int32_t pad_read_state(int32_t handle, PadData *data) {
    if (handle!=PAD_HANDLE || !opened) return ERR_INVALID_HANDLE;
    if (!data) return ERR_INVALID_ARG;
    pthread_mutex_lock(&lock);
    sample(data); ++reads;
    pthread_mutex_unlock(&lock);
    return 0;
}
/* Buffered read: the port samples once per call, so one entry is returned. */
static ABI int32_t pad_read(int32_t handle, PadData *data, int32_t count) {
    if (handle!=PAD_HANDLE || !opened) return ERR_INVALID_HANDLE;
    if (!data || count<1 || count>64) return ERR_INVALID_ARG;
    pad_read_state(handle,data);
    return 1;
}
static ABI int32_t pad_info(int32_t handle, ControllerInfo *info) {
    if (handle!=PAD_HANDLE || !opened) return ERR_INVALID_HANDLE;
    if (!info) return ERR_INVALID_ARG;
    memset(info,0,sizeof(*info));
    info->pixel_density=44.86f; info->resolution_x=1920; info->resolution_y=943;
    info->dead_zone_left=info->dead_zone_right=2;
    info->connection_type=0; info->connected=1; info->device_class=0;
    pthread_mutex_lock(&lock);
    current_gamepad();
    info->connected_count=connected_count ? connected_count : 1;
    pthread_mutex_unlock(&lock);
    return 0;
}
static ABI int32_t pad_vibration(int32_t handle, const uint8_t *param) {
    if (handle!=PAD_HANDLE || !opened) return ERR_INVALID_HANDLE;
    if (!param) return ERR_INVALID_ARG;
    pthread_mutex_lock(&lock);
    SDL_Gamepad *g=current_gamepad();
    if (g) SDL_RumbleGamepad(g,(uint16_t)(param[0]*257),(uint16_t)(param[1]*257),1000);
    pthread_mutex_unlock(&lock);
    return 0;
}
static ABI int32_t pad_ok_handle(int32_t handle) { return handle==PAD_HANDLE && opened ? 0 : ERR_INVALID_HANDLE; }
static ABI int32_t pad_ok_handle_flag(int32_t handle, uint8_t flag) { (void)flag; return pad_ok_handle(handle); }

static ABI int32_t pad_light_bar(int32_t handle, const uint8_t *rgb) {
    if (handle!=PAD_HANDLE || !opened) return ERR_INVALID_HANDLE;
    (void)rgb; return 0;
}
static const RuntimeExport exports[]={
    {"scePadSetLightBar",pad_light_bar}, {"scePadResetLightBar",pad_ok_handle},
    {"scePadInit",pad_init}, {"scePadOpen",pad_open}, {"scePadClose",pad_close},
    {"scePadReadState",pad_read_state}, {"scePadRead",pad_read},
    {"scePadGetControllerInformation",pad_info}, {"scePadSetVibration",pad_vibration},
    {"scePadResetOrientation",pad_ok_handle},
    {"scePadSetAngularVelocityDeadbandState",pad_ok_handle_flag}, {"scePadSetTiltCorrectionState",pad_ok_handle_flag},
    {"scePadSetMotionSensorState",pad_ok_handle_flag},
};
uintptr_t runtime_pad_resolve(const char *name) { return RUNTIME_LOOKUP(exports,name); }
void runtime_pad_report(void) {
    printf("Runtime: pad reads=%zu (mouse captured in %zu), gamepad=%s\n",reads,mouse_samples,
           gamepad ? SDL_GetGamepadName(gamepad) : "none");
}
