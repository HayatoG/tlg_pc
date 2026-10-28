// Regression: a guest readback arriving after the initial pending check must not mutate
// cache state while the draw recorder still owns it. Exercise the production dispatch loop.
#include <cassert>
#include <cstdio>
#include <functional>
#include <mutex>
#include <queue>
#include "video_core/amdgpu/queued_commands.h"

struct Fixture {
    std::queue<std::function<void()>> commands;
    std::mutex queue_mutex;
    bool recorder_busy = true;
    bool late_arrival = false;
    bool unsafe_cache_access = false;
    unsigned drained = 0, called = 0;

    void Add() {
        commands.push([this] {
            unsafe_cache_access |= recorder_busy;
            ++called;
            // Model another packet already in flight before the next cache operation.
            recorder_busy = true;
        });
    }
    bool Pending() {
        const bool pending = !commands.empty();
        if (late_arrival) {
            late_arrival = false;
            Add(); // producer arrives just after the consumer observed an empty queue
        }
        return pending;
    }
    auto Take() {
        std::scoped_lock lock{queue_mutex};
        auto callback = std::move(commands.front());
        commands.pop();
        return callback;
    }
    void Drain() {
        // Waiting for the recorder must not hold the submit/queue mutex.
        assert(queue_mutex.try_lock());
        queue_mutex.unlock();
        recorder_busy = false;
        ++drained;
    }
    void Run() {
        AmdGpu::ProcessQueuedCommands([this] { return Pending(); },
                                    [this] { return Take(); }, [this] { Drain(); });
    }
};

int main() {
    // Confirm the old pre-loop check has exactly the reported unsafe arrival window.
    Fixture legacy;
    legacy.late_arrival = true;
    if (legacy.Pending()) legacy.Drain();
    while (legacy.Pending()) legacy.Take()();
    assert(legacy.called == 1 && legacy.unsafe_cache_access && legacy.drained == 0);

    Fixture late;
    late.late_arrival = true;
    late.Run(); // an arrival after the last check can safely wait until the next poll
    late.Run();
    assert(late.called == 1 && late.drained == 1 && !late.unsafe_cache_access);

    Fixture batch;
    for (unsigned i = 0; i < 10000; ++i) batch.Add();
    batch.Run();
    assert(batch.called == 10000 && batch.drained == 10000 && !batch.unsafe_cache_access);
    batch.Run();
    assert(batch.drained == 10000); // no spurious drain for an empty queue

    Fixture during_take;
    during_take.Add();
    AmdGpu::ProcessQueuedCommands(
        [&] { return !during_take.commands.empty(); },
        [&] {
            auto callback = during_take.Take();
            if (during_take.called == 0) during_take.Add();
            return callback;
        },
        [&] { during_take.Drain(); });
    assert(during_take.called == 2 && during_take.drained == 2 &&
           !during_take.unsafe_cache_access);
    std::puts("PASS: legacy late-arrival race reproduced; every queued callback drains first, "
              "outside the queue lock (10000-command regression)");
}
