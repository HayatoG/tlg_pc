#pragma once
#include <stdint.h>
#include <string.h>

/* Redirect an invalid zero-byte format to the resource constructor's own error cleanup. */
static int format_guard_rel(unsigned char *end, unsigned char *target, int32_t *out) {
    intptr_t d = (intptr_t)target - (intptr_t)end;
    if (d < INT32_MIN || d > INT32_MAX) return 0;
    *out = (int32_t)d;
    return 1;
}
static int format_guard_install(unsigned char *site, unsigned char *stub,
                                unsigned char *normal, unsigned char *failure, unsigned char *counter) {
    static const unsigned char expected[] = {0x41,0x8b,0x84,0x24,0x80,0x01,0x00,0x00};
    unsigned char code[] = {0x85,0xf6,0x0f,0x85,0,0,0,0,
                            0xf0,0x48,0xff,0x05,0,0,0,0, 0xe9,0,0,0,0,
                            0x41,0x8b,0x84,0x24,0x80,0x01,0x00,0x00, 0xe9,0,0,0,0};
    int32_t to_stub, to_valid, to_counter, to_failure, to_normal;
    if (memcmp(site,expected,sizeof expected) ||
        ((uintptr_t)counter & 7) ||
        !format_guard_rel(site+5,stub,&to_stub) ||
        !format_guard_rel(stub+8,stub+21,&to_valid) ||
        !format_guard_rel(stub+16,counter,&to_counter) ||
        !format_guard_rel(stub+21,failure,&to_failure) ||
        !format_guard_rel(stub+34,normal,&to_normal)) return 0;
    memcpy(code+4,&to_valid,4);
    memcpy(code+12,&to_counter,4);
    memcpy(code+17,&to_failure,4);
    memcpy(code+30,&to_normal,4);
    memcpy(stub,code,sizeof code);
    site[0]=0xe9; memcpy(site+1,&to_stub,4); memset(site+5,0x90,3);
    return 1;
}
