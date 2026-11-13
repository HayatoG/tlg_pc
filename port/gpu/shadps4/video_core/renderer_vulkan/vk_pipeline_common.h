// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include "shader_recompiler/profile.h"
#include "shader_recompiler/runtime_info.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <atomic>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <string_view>

#include <boost/container/small_vector.hpp>

namespace Shader {
struct Info;
struct PushData;
} // namespace Shader

namespace Vulkan {

static constexpr auto AllGraphicsStageBits =
    vk::ShaderStageFlagBits::eVertex | vk::ShaderStageFlagBits::eTessellationControl |
    vk::ShaderStageFlagBits::eTessellationEvaluation | vk::ShaderStageFlagBits::eGeometry |
    vk::ShaderStageFlagBits::eFragment;

class Instance;
class Scheduler;
class DescriptorHeap;

/// tlg: whether creating a pipeline that failed with `result` on `attempt` (from 1) is tried
/// again, after waiting a little longer each time for the driver to recover.
bool RetryPipelineCreation(vk::Result result, u32 attempt, std::string_view kind,
                           std::string_view name);

class Pipeline {
public:
    Pipeline(const Instance& instance, Scheduler& scheduler, DescriptorHeap& desc_heap,
             const Shader::Profile& profile, vk::PipelineCache pipeline_cache,
             bool is_compute = false);
    virtual ~Pipeline();

    vk::Pipeline Handle() const noexcept {
        if (build) [[unlikely]] {
            return BuiltHandle();
        }
        return *pipeline;
    }

    /// tlg: false while a compute pipeline met in game is still being built on a compiler
    /// thread (vk_compute_pipeline.cpp). Handle() then waits for it.
    [[nodiscard]] bool IsBuilt() const noexcept {
        return !build || build->handle.load(std::memory_order_acquire) != VK_NULL_HANDLE;
    }

    /// tlg: binds recorded for the Vulkan recording thread of pipelines still being built.
    static inline std::atomic<u32> deferred_binds{0};

    vk::PipelineLayout GetLayout() const noexcept {
        return *pipeline_layout;
    }

    auto GetStages() const {
        static_assert(static_cast<u32>(Shader::SwStage::Compute) == Shader::MaxStageTypes - 1);
        if (is_compute) {
            return std::span{stages.cend() - 1, stages.cend()};
        } else {
            return std::span{stages.cbegin(), stages.cend() - 1};
        }
    }

    const Shader::Info& GetStage(Shader::SwStage stage) const noexcept {
        return *stages[u32(stage)];
    }

    /// tlg: the fragment shader's hash, 0 for depth-only pipelines.
    u64 FragmentHash() const noexcept {
        const auto* fs = stages[u32(Shader::SwStage::Fragment)];
        return fs ? fs->pgm_hash : 0;
    }

    bool IsCompute() const {
        return is_compute;
    }

    using DescriptorWrites = std::vector<vk::WriteDescriptorSet>;
    void BindResources(DescriptorWrites& set_writes, const Shader::PushData& push_data) const;

protected:
    [[nodiscard]] std::string GetDebugString() const;

    /// tlg: a pipeline built on a compiler thread. `handle` is what Handle() returns: null until
    /// built, or the one built without optimizations until the optimized `result` replaces it.
    struct Build {
        std::atomic<VkPipeline> handle{VK_NULL_HANDLE};
        std::atomic<bool> done{false};
        std::mutex mutex;
        std::condition_variable cv;
        vk::UniquePipeline result; ///< written by the compiler thread before `done`
    };
    /// Set in the constructor, before other threads see the pipeline, and never reset.
    std::shared_ptr<Build> build;

    const Instance& instance;
    Scheduler& scheduler;
    DescriptorHeap& desc_heap;
    const Shader::Profile& profile;
    vk::UniquePipeline pipeline;
    vk::UniquePipelineLayout pipeline_layout;
    vk::UniqueDescriptorSetLayout desc_layout;
    std::array<const Shader::Info*, Shader::MaxStageTypes> stages{};
    bool uses_push_descriptors{};
    bool is_compute;

private:
    vk::Pipeline BuiltHandle() const;
};

} // namespace Vulkan
