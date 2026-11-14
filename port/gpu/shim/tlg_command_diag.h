#pragma once
#include <atomic>
#include <cstdint>

namespace TlgStats {
inline std::atomic<std::uint64_t> cmd_drain_groups{0}, cmd_drain_queued{0}, cmd_drain_max{0};
inline std::atomic<std::uint64_t> buffer_empty{0}, buffer_copies{0}, buffer_ranges{0}, buffer_staged_bytes{0};
inline std::atomic<std::uint64_t> dirty_page_empty{0}, dirty_page_small{0}, dirty_page_partial{0}, dirty_page_full{0};
inline std::atomic<std::uint64_t> hot_block_inside{0}, hot_block_outside{0}, hot_block_unknown{0};
}
