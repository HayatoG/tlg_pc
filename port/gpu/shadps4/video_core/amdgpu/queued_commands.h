// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

namespace AmdGpu {

// A producer may enqueue work after any pending() check. Transfer cache ownership only
// after taking each command, before its callback can inspect or mutate GPU-owned state.
// take() must release the queue lock before returning: drain() may wait for another thread.
template <typename Pending, typename Take, typename Drain>
void ProcessQueuedCommands(Pending&& pending, Take&& take, Drain&& drain) {
    while (pending()) {
        auto callback = take();
        drain();
        callback();
    }
}

} // namespace AmdGpu
