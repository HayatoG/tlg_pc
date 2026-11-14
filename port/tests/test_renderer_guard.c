#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <windows.h>
#include "renderer_guard.h"

typedef int (*Entry)(unsigned, void *);
struct Table { void **entries; uint32_t count; };

static void rel32(unsigned char *at, unsigned char *target) {
    int32_t displacement = (int32_t)(target - (at + 4));
    memcpy(at, &displacement, 4);
}

int main(void) {
    unsigned char *m = VirtualAlloc(NULL, 3 * 4096, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    assert(m);
    /* Win64 entry: save nonvolatile registers, set up the guest inputs, then jump to the hook. */
    const unsigned char wrapper[] = {0x41,0x55,0x57,0x89,0xc8,0x48,0x8b,0x0a,0xe9,0,0,0,0};
    memcpy(m, wrapper, sizeof wrapper); rel32(m+9, m+0x100);
    const unsigned char expected[] = {0x4c,0x8b,0x2c,0xc1,0x49,0x8d,0x7d,0x10,0xe8,0xaf,0x4b,0x62,0xff};
    memcpy(m+0x100, expected, sizeof expected);
    const unsigned char success[] = {0x5f,0x41,0x5d,0xb8,1,0,0,0,0xc3};
    const unsigned char skip[] = {0x5f,0x41,0x5d,0x31,0xc0,0xc3};
    memcpy(m+0x10d, success, sizeof success); memcpy(m+0x180, skip, sizeof skip);
    /* Stand-in lock records its argument and call count. */
    const unsigned char lock[] = {0x48,0x89,0x3d,0,0,0,0,0xff,0x05,0,0,0,0,0xc3};
    memcpy(m+0x190,lock,sizeof lock); rel32(m+0x193,m+0x2010); rel32(m+0x199,m+0x2018);
    assert(renderer_guard_install(m+0x100,m+0x1000,m+0x190,m+0x10d,m+0x180,m+0x2000));
    DWORD old;
    assert(VirtualProtect(m,2 * 4096,PAGE_EXECUTE_READ,&old));
    assert(FlushInstructionCache(GetCurrentProcess(),m,2 * 4096));
    void *entries[] = {(void *)0x1000, NULL};
    struct Table table = {entries, 2};
    assert(((Entry)m)(0, &table) == 1);
    assert(*(uintptr_t *)(m+0x2010) == 0x1010);
    assert(*(uint32_t *)(m+0x2018) == 1);
    assert(*(uint64_t *)(m+0x2000) == 0);
    assert(((Entry)m)(1, &table) == 0);
    assert(((Entry)m)(2, &table) == 0);
    assert(((Entry)m)(UINT32_MAX, &table) == 0);
    struct Table empty = {NULL, 0};
    assert(((Entry)m)(0, &empty) == 0);
    assert(*(uint32_t *)(m+0x2018) == 1);
    assert(*(uint64_t *)(m+0x2000) == 4);
    assert(!renderer_guard_install(m+0x100,m+0x1000,m+0x190,m+0x10d,m+0x180,m+0x2000));
    VirtualFree(m,0,MEM_RELEASE);
    puts("renderer guard: valid, null, bounds, and signature checks passed");
    return 0;
}
