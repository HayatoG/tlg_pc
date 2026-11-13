#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
enum { TLG_OP_NONE, TLG_OP_COPY, TLG_OP_FILL, TLG_OP_MOVE };
typedef struct TlgMemoryOp {
    uintptr_t dst, src;
    uint64_t size;
    int kind;
} TlgMemoryOp;
TlgMemoryOp tlg_memory_op_enter(int kind, uintptr_t dst, uintptr_t src, uint64_t size);
void tlg_memory_op_leave(TlgMemoryOp previous);
int tlg_memory_op_classify(uintptr_t address);
TlgMemoryOp tlg_memory_op_current(void);
uintptr_t tlg_fault_site_enter(uintptr_t site);
void tlg_fault_site_leave(uintptr_t previous);
uintptr_t tlg_fault_site_get(void);
uintptr_t tlg_fault_target_enter(uintptr_t target);
void tlg_fault_target_leave(uintptr_t previous);
uintptr_t tlg_fault_target_get(void);
#ifdef __cplusplus
}
#endif
