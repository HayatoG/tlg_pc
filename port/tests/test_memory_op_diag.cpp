#include "tlg_memory_op_diag.h"
#include <cassert>
#include <thread>

int main() {
    assert(tlg_memory_op_classify(0x1000) == TLG_OP_NONE);
    const auto previous = tlg_memory_op_enter(TLG_OP_COPY, 0x1000, 0x5000, 64);
    assert(tlg_memory_op_classify(0x1000) == TLG_OP_COPY);
    assert(tlg_memory_op_classify(0x103f) == TLG_OP_COPY);
    assert(tlg_memory_op_classify(0x1040) == TLG_OP_NONE);
    std::thread other([] { assert(tlg_memory_op_classify(0x1000) == TLG_OP_NONE); });
    other.join();
    const auto nested = tlg_memory_op_enter(TLG_OP_FILL, 0x2000, 0, 16);
    assert(tlg_memory_op_classify(0x1000) == TLG_OP_NONE);
    assert(tlg_memory_op_classify(0x2000) == TLG_OP_FILL);
    tlg_memory_op_leave(nested);
    assert(tlg_memory_op_classify(0x1000) == TLG_OP_COPY);
    tlg_memory_op_leave(previous);
    assert(tlg_memory_op_classify(0x1000) == TLG_OP_NONE);
    assert(tlg_fault_site_get() == 0);
    const auto old = tlg_fault_site_enter(0x1234);
    assert(tlg_fault_site_get() == 0x1234);
    std::thread site_other([] { assert(tlg_fault_site_get() == 0); });
    site_other.join();
    const auto nested_site = tlg_fault_site_enter(0x5678);
    tlg_fault_site_leave(nested_site);
    assert(tlg_fault_site_get() == 0x1234);
    tlg_fault_site_leave(old);
    assert(tlg_fault_site_get() == 0);
    const auto old_target = tlg_fault_target_enter(0x12345678);
    assert(tlg_fault_target_get() == 0x12345678);
    std::thread target_other([] { assert(tlg_fault_target_get() == 0); });
    target_other.join();
    const auto nested_target = tlg_fault_target_enter(0x42);
    tlg_fault_target_leave(nested_target);
    assert(tlg_fault_target_get() == 0x12345678);
    tlg_fault_target_leave(old_target);
    assert(tlg_fault_target_get() == 0);
}
