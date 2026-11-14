#pragma once
#include <cstdint>
namespace TlgReadback {
inline std::uint64_t WindowBytes(const char* value) {
    constexpr std::uint64_t fallback = 512 * 1024;
    if (!value || !*value) return fallback;
    unsigned n = 0;
    for (; *value; ++value) {
        if (*value < '0' || *value > '9' || n > 4096) return fallback;
        n = n * 10 + unsigned(*value - '0');
    }
    if (n < 64 || n > 4096 || (n & (n - 1)) != 0) return fallback;
    return std::uint64_t{n} * 1024;
}
}
