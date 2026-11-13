// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

namespace Vulkan {
// Called by the render thread, before the first asynchronous pipeline is queued.
class PipelineCacheSeed {
public:
    template <class Merge>
    void Ensure(bool async_enabled, Merge&& merge) {
        if (!async_enabled || seeded) return;
        merge();
        seeded = true;
    }
private:
    bool seeded = false;
};
} // namespace Vulkan
