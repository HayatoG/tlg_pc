#pragma once
#include <cstdint>
namespace TlgStats {
enum class DirtyPageBucket { Empty, AtMost16, Partial, Full };
constexpr DirtyPageBucket ClassifyDirtyPage(std::uint64_t bytes) {
    return bytes == 0 ? DirtyPageBucket::Empty : bytes <= 16 ? DirtyPageBucket::AtMost16
        : bytes < 4096 ? DirtyPageBucket::Partial : DirtyPageBucket::Full;
}
constexpr bool RangeInsideBlock(std::uint64_t start, std::uint64_t end,
                                std::uint64_t block_start, std::uint64_t block_end) {
    return start >= block_start && end <= block_end;
}
}
