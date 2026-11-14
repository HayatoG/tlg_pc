// SPDX-FileCopyrightText: Copyright 2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <cstddef>

#include <vulkan/vulkan.hpp>

namespace VideoCore {

inline bool IsBarrierMergeEnabled(const char* value) {
    return value && value[0] == '1' && value[1] == '\0';
}

template <typename Container>
void MergeAdjacentBarriers(Container& barriers, std::size_t first) {
    if (barriers.size() < first + 2) {
        return;
    }
    const auto merge_pass = [&](bool layers) {
        std::size_t out = first;
        for (std::size_t i = first + 1; i < barriers.size(); ++i) {
            auto& prev = barriers[out];
            const auto cur = barriers[i];
            auto& pr = prev.subresourceRange;
            const auto& cr = cur.subresourceRange;
            const bool same_transition =
                prev.image == cur.image && pr.aspectMask == cr.aspectMask &&
                prev.srcStageMask == cur.srcStageMask && prev.srcAccessMask == cur.srcAccessMask &&
                prev.dstStageMask == cur.dstStageMask && prev.dstAccessMask == cur.dstAccessMask &&
                prev.oldLayout == cur.oldLayout && prev.newLayout == cur.newLayout &&
                prev.srcQueueFamilyIndex == cur.srcQueueFamilyIndex &&
                prev.dstQueueFamilyIndex == cur.dstQueueFamilyIndex;
            const bool adjacent =
                layers ? (pr.baseMipLevel == cr.baseMipLevel &&
                          pr.levelCount == cr.levelCount &&
                          pr.baseArrayLayer + pr.layerCount == cr.baseArrayLayer)
                       : (pr.baseArrayLayer == cr.baseArrayLayer &&
                          pr.layerCount == cr.layerCount &&
                          pr.baseMipLevel + pr.levelCount == cr.baseMipLevel);
            if (same_transition && adjacent) {
                if (layers) {
                    pr.layerCount += cr.layerCount;
                } else {
                    pr.levelCount += cr.levelCount;
                }
                continue;
            }
            barriers[++out] = cur;
        }
        barriers.erase(barriers.begin() + (out + 1), barriers.end());
    };
    merge_pass(true);
    merge_pass(false);
}

} // namespace VideoCore
