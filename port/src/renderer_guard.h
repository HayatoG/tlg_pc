#pragma once
#include <stdint.h>
#include <string.h>

/* Bounds/null guard for the CUSA03627 1.03 renderer's GPU result list. The caller must
 * provide a fresh executable stub, and validate the surrounding game version separately. */
static int renderer_guard_disp(unsigned char *end, const unsigned char *target, int32_t *out) {
    intptr_t d = (intptr_t)target - (intptr_t)end;
    if (d < INT32_MIN || d > INT32_MAX) return 0;
    *out = (int32_t)d;
    return 1;
}

static int renderer_guard_install(unsigned char *site, unsigned char *stub,
                                  unsigned char *lock, unsigned char *normal,
                                  unsigned char *skip, unsigned char *counter) {
    static const unsigned char expected[] = {
        0x4c,0x8b,0x2c,0xc1,0x49,0x8d,0x7d,0x10,0xe8,0xaf,0x4b,0x62,0xff
    };
    /* Invalid entries branch to an atomic counter and then the loop increment. */
    unsigned char code[] = {
        0x3b,0x42,0x08, 0x0f,0x83,0,0,0,0, 0x4c,0x8b,0x2c,0xc1,
        0x4d,0x85,0xed, 0x0f,0x84,0,0,0,0, 0x49,0x8d,0x7d,0x10,
        0xe8,0,0,0,0, 0xe9,0,0,0,0,
        0xf0,0x48,0xff,0x05,0,0,0,0, 0xe9,0,0,0,0
    };
    int32_t to_stub, bound_skip, null_skip, to_lock, to_normal, to_counter, to_skip;
    if (memcmp(site,expected,sizeof expected) ||
        ((uintptr_t)counter & 7) ||
        !renderer_guard_disp(site+5,stub,&to_stub) ||
        !renderer_guard_disp(stub+9,stub+36,&bound_skip) ||
        !renderer_guard_disp(stub+22,stub+36,&null_skip) ||
        !renderer_guard_disp(stub+31,lock,&to_lock) ||
        !renderer_guard_disp(stub+36,normal,&to_normal) ||
        !renderer_guard_disp(stub+44,counter,&to_counter) ||
        !renderer_guard_disp(stub+49,skip,&to_skip)) return 0;
    memcpy(code+5,&bound_skip,4); memcpy(code+18,&null_skip,4);
    memcpy(code+27,&to_lock,4); memcpy(code+32,&to_normal,4);
    memcpy(code+40,&to_counter,4); memcpy(code+45,&to_skip,4);
    memcpy(stub,code,sizeof code);
    site[0]=0xe9; memcpy(site+1,&to_stub,4); memset(site+5,0x90,sizeof expected-5);
    return 1;
}
