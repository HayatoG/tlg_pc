#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <windows.h>
#include "format_guard.h"

typedef int (*Entry)(unsigned, void *);
static void rel32(unsigned char *at, unsigned char *target) {
    int32_t displacement = (int32_t)(target - (at + 4));
    memcpy(at, &displacement, 4);
}
int main(void) {
    unsigned char *m = VirtualAlloc(NULL, 12288, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    assert(m);
    /* Preserve Win64 nonvolatile registers and load the guest divisor and resource. */
    const unsigned char wrapper[] = {0x41,0x54,0x56,0x49,0x89,0xd4,0x89,0xce,0xe9,0,0,0,0};
    memcpy(m, wrapper, sizeof wrapper); rel32(m+9, m+0x100);
    const unsigned char expected[] = {0x41,0x8b,0x84,0x24,0x80,0x01,0x00,0x00};
    memcpy(m+0x100, expected, sizeof expected);
    const unsigned char normal[] = {0x31,0xd2,0xf7,0xf6,0x5e,0x41,0x5c,0xc3};
    const unsigned char failure[] = {0xb8,0xfe,0xff,0xff,0xff,0x5e,0x41,0x5c,0xc3};
    memcpy(m+0x108, normal, sizeof normal); memcpy(m+0x180, failure, sizeof failure);
    assert(format_guard_install(m+0x100,m+0x1000,m+0x108,m+0x180,m+0x2000));
    DWORD old;
    assert(VirtualProtect(m,8192,PAGE_EXECUTE_READ,&old));
    assert(FlushInstructionCache(GetCurrentProcess(),m,8192));
    unsigned char resource[0x184] = {0};
    *(uint32_t *)(resource+0x180) = 64000;
    assert(((Entry)m)(4,resource) == 16000);
    assert(*(uint64_t *)(m+0x2000) == 0);
    assert(((Entry)m)(0,resource) == -2);
    assert(*(uint64_t *)(m+0x2000) == 1);
    assert(((Entry)m)(0,resource) == -2);
    assert(((Entry)m)(UINT32_MAX,resource) == 0);
    assert(*(uint64_t *)(m+0x2000) == 2);
    assert(!format_guard_install(m+0x100,m+0x1000,m+0x108,m+0x180,m+0x2000));
    VirtualFree(m,0,MEM_RELEASE);
    puts("format guard: valid divisor, zero divisor and signature verified");
}
