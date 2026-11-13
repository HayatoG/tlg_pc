#pragma once
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <mutex>
#include "tlg_memory_op_diag.h"

namespace TlgStats {
struct ReuseCounts {
    std::uint64_t first{}, fast{}, medium{}, slow{}, old{}, writes{}, collisions{}, crossing{};
    std::uint64_t copy{}, fill{}, move{}, other{}, eligible64{};
};
template <std::size_t N> class FaultSiteCounts {
public:
    struct Site { std::uint64_t key{}, count{}; };
    struct Result { std::array<Site, N> sites{}; std::uint64_t overflow{}; };
    void Note(std::uint64_t key) {
        for (auto& site : result.sites) {
            if (site.count && site.key == key) { ++site.count; return; }
            if (!site.count) { site = {key, 1}; return; }
        }
        ++result.overflow;
    }
    Result Take() { auto out = result; result = {}; return out; }
private:
    Result result{};
};

// Direct-mapped, bounded diagnostic: collisions lose history rather than reporting false reuse.
template <std::size_t N> class ReadbackReuse {
    struct Entry { std::uint64_t page{}, ms{}; bool occupied{}; };
    std::array<Entry, N> entries{};
    ReuseCounts counts{};
public:
    void Note(std::uint64_t address, std::uint64_t now_ms, bool write, std::uint64_t size = 1) {
        const auto page = address >> 12;
        auto& entry = entries[page % N];
        counts.writes += write;
        counts.crossing += size > 4096 - (address & 4095);
        if (!entry.occupied || entry.page != page || now_ms < entry.ms) {
            ++counts.first;
            if (entry.occupied && entry.page != page) ++counts.collisions;
        } else {
            const auto elapsed = now_ms - entry.ms;
            if (elapsed < 16) ++counts.fast;
            else if (elapsed < 100) ++counts.medium;
            else if (elapsed < 1000) ++counts.slow;
            else ++counts.old;
        }
        entry = {page, now_ms, true};
    }
    void NoteOrigin(TlgMemoryOp op) {
        switch (op.kind) {
        case TLG_OP_COPY: ++counts.copy; break;
        case TLG_OP_FILL: ++counts.fill; break;
        case TLG_OP_MOVE: ++counts.move; break;
        default: ++counts.other; return;
        }
        const auto distance = op.dst >= op.src ? op.dst - op.src : op.src - op.dst;
        if (op.size >= 64 && (op.kind != TLG_OP_MOVE || distance >= op.size))
            ++counts.eligible64;
    }
    ReuseCounts Take() { auto result = counts; counts = {}; return result; }
};

inline bool ReadbackReuseEnabled() {
    static const bool enabled = [] { const auto* e = std::getenv("TLG_READBACK_REUSE_DIAG");
        return e && e[0] == '1' && e[1] == '\0'; }();
    return enabled;
}
inline std::mutex reuse_mutex;
inline ReadbackReuse<65536> reuse_tracker;
inline FaultSiteCounts<64> fault_sites;
inline std::uint32_t sample_rng = 0x517cc1b7;
inline void NoteReadbackReuse(std::uint64_t address, std::uint64_t size, bool write) {
    TlgMemoryOp op{};
    if (write && tlg_memory_op_classify(address)) op = tlg_memory_op_current();
    std::scoped_lock lock{reuse_mutex};
    const auto now = std::chrono::steady_clock::now().time_since_epoch();
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now).count();
    reuse_tracker.Note(address, static_cast<std::uint64_t>(ms), write, size);
    if (write) {
        reuse_tracker.NoteOrigin(op);
        sample_rng ^= sample_rng << 13; sample_rng ^= sample_rng >> 17; sample_rng ^= sample_rng << 5;
        if ((sample_rng & 15) == 0) fault_sites.Note(tlg_fault_site_get());
    }
}
inline auto TakeFaultSites() {
    std::scoped_lock lock{reuse_mutex};
    return fault_sites.Take();
}
inline ReuseCounts TakeReadbackReuse() {
    std::scoped_lock lock{reuse_mutex};
    return reuse_tracker.Take();
}
} // namespace TlgStats
