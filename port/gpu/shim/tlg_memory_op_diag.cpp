#include "tlg_memory_op_diag.h"
static thread_local TlgMemoryOp current{};
static thread_local uintptr_t fault_site{};
static thread_local uintptr_t fault_target{};
extern "C" TlgMemoryOp tlg_memory_op_enter(int kind, uintptr_t dst, uintptr_t src, uint64_t size) {
    const auto previous = current;
    current = {dst, src, size, kind};
    return previous;
}
extern "C" void tlg_memory_op_leave(TlgMemoryOp previous) { current = previous; }
extern "C" int tlg_memory_op_classify(uintptr_t address) {
    return current.kind && address >= current.dst && address - current.dst < current.size
        ? current.kind : TLG_OP_NONE;
}
extern "C" TlgMemoryOp tlg_memory_op_current(void) { return current; }
extern "C" uintptr_t tlg_fault_site_enter(uintptr_t site) {
    const auto previous = fault_site; fault_site = site; return previous;
}
extern "C" void tlg_fault_site_leave(uintptr_t previous) { fault_site = previous; }
extern "C" uintptr_t tlg_fault_site_get(void) { return fault_site; }
extern "C" uintptr_t tlg_fault_target_enter(uintptr_t target) {
    const auto previous = fault_target; fault_target = target; return previous;
}
extern "C" void tlg_fault_target_leave(uintptr_t previous) { fault_target = previous; }
extern "C" uintptr_t tlg_fault_target_get(void) { return fault_target; }
