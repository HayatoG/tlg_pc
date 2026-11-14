#include "pipeline_cache_seed.h"

#include <cassert>

int main() {
    Vulkan::PipelineCacheSeed seed;
    int calls = 0;
    auto merge = [&] { ++calls; };
    seed.Ensure(false, merge);
    seed.Ensure(false, merge);
    assert(calls == 0);
    seed.Ensure(true, merge);
    assert(calls == 1);
    seed.Ensure(false, merge);
    seed.Ensure(true, merge);
    assert(calls == 1);

    Vulkan::PipelineCacheSeed retry;
    try {
        retry.Ensure(true, [] { throw 1; });
        assert(false);
    } catch (int) {}
    retry.Ensure(true, merge);
    assert(calls == 2);
}
