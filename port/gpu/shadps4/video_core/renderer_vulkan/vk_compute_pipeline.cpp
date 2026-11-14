// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <chrono>
#include <cstdlib>

#include <boost/container/small_vector.hpp>

#include "common/logging/log.h"
#include "shader_recompiler/info.h"
#include "video_core/renderer_vulkan/vk_async_compiler.h"
#include "video_core/renderer_vulkan/vk_compute_pipeline.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"

namespace Vulkan {

ComputePipeline::ComputePipeline(const Instance& instance, Scheduler& scheduler,
                                 DescriptorHeap& desc_heap, const Shader::Profile& profile,
                                 vk::PipelineCache pipeline_cache, ComputePipelineKey compute_key_,
                                 const Shader::Info& info_, vk::ShaderModule module,
                                 SerializationSupport& sdata, bool preloading /*=false*/,
                                 const ComputeBuilder* builder /*=nullptr*/)
    : Pipeline{instance, scheduler, desc_heap, profile, pipeline_cache, true},
      compute_key{compute_key_} {
    auto& info = stages[int(Shader::SwStage::Compute)];
    info = &info_;
    const auto debug_str = GetDebugString();

    u32 binding{};
    boost::container::small_vector<vk::DescriptorSetLayoutBinding, 32> bindings;
    for (const auto& buffer : info->buffers) {
        // During deserialization, we don't have access to the UD to fetch sharp data. To address
        // this properly we need to track shaprs or portion of them in `sdata`, but since we're
        // interested only in "is storage" flag (which is not even effective atm), we can take a
        // shortcut there.
        const auto sharp = preloading ? AmdGpu::Buffer{} : buffer.GetSharp(*info);
        bindings.push_back({
            .binding = binding++,
            .descriptorType = vk::DescriptorType::eStorageBuffer,
            .descriptorCount = 1,
            .stageFlags = vk::ShaderStageFlagBits::eCompute,
        });
    }
    for (const auto& image : info->images) {
        const u32 num_bindings = image.NumBindings(*info);
        bindings.push_back({
            .binding = binding,
            .descriptorType = image.is_written ? vk::DescriptorType::eStorageImage
                                               : vk::DescriptorType::eSampledImage,
            .descriptorCount = num_bindings,
            .stageFlags = vk::ShaderStageFlagBits::eCompute,
        });
        binding += num_bindings;
    }
    for (const auto& sampler : info->samplers) {
        bindings.push_back({
            .binding = binding++,
            .descriptorType = vk::DescriptorType::eSampler,
            .descriptorCount = 1,
            .stageFlags = vk::ShaderStageFlagBits::eCompute,
        });
    }

    const vk::PushConstantRange push_constants = {
        .stageFlags = vk::ShaderStageFlagBits::eCompute,
        .offset = 0,
        .size = sizeof(Shader::PushData),
    };

    uses_push_descriptors = binding < instance.MaxPushDescriptors();
    const auto flags = uses_push_descriptors
                           ? vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR
                           : vk::DescriptorSetLayoutCreateFlagBits{};
    const vk::DescriptorSetLayoutCreateInfo desc_layout_ci = {
        .flags = flags,
        .bindingCount = static_cast<u32>(bindings.size()),
        .pBindings = bindings.data(),
    };
    const auto device = instance.GetDevice();
    auto [descriptor_set_result, descriptor_set] =
        device.createDescriptorSetLayoutUnique(desc_layout_ci);
    ASSERT_MSG(descriptor_set_result == vk::Result::eSuccess,
               "Failed to create compute descriptor set layout: {}",
               vk::to_string(descriptor_set_result));
    desc_layout = std::move(descriptor_set);

    const vk::DescriptorSetLayout set_layout = *desc_layout;
    const vk::PipelineLayoutCreateInfo layout_info = {
        .setLayoutCount = 1U,
        .pSetLayouts = &set_layout,
        .pushConstantRangeCount = 1U,
        .pPushConstantRanges = &push_constants,
    };
    auto [layout_result, layout] = instance.GetDevice().createPipelineLayoutUnique(layout_info);
    ASSERT_MSG(layout_result == vk::Result::eSuccess,
               "Failed to create compute pipeline layout: {}", vk::to_string(layout_result));
    pipeline_layout = std::move(layout);
    SetObjectName(device, *pipeline_layout, "Compute PipelineLayout {}", debug_str);

    // Runs on the compiler threads too: it only uses what stays fixed after construction and
    // the layout, which the destructor keeps alive until the build is done. Returns no pipeline
    // when one may only come from the driver's cache and it isn't there.
    const auto create = [&instance, module, layout = *pipeline_layout, debug_str](
                            vk::PipelineCache cache,
                            vk::PipelineCreateFlags flags) -> vk::UniquePipeline {
        const vk::PipelineShaderStageRequiredSubgroupSizeCreateInfo subgroup_size_ci = {
            .requiredSubgroupSize = 64,
        };
        const vk::ComputePipelineCreateInfo compute_pipeline_ci = {
            .flags = flags,
            .stage{
                // tlg: the stage must be in requiredSubgroupSizeStages for this to be valid; the
                // profile's subgroup size (vk_pipeline_cache.cpp) is picked to match.
                .pNext = instance.IsRequiredSubgroupSize64ValidFor(
                             vk::ShaderStageFlagBits::eCompute)
                             ? &subgroup_size_ci
                             : nullptr,
                .stage = vk::ShaderStageFlagBits::eCompute,
                .module = module,
                .pName = "main",
            },
            .layout = layout,
        };
        const auto device = instance.GetDevice();
        auto created = device.createComputePipelineUnique(cache, compute_pipeline_ci);
        for (u32 attempt = 1;
             RetryPipelineCreation(created.result, attempt, "compute", debug_str); ++attempt) {
            created = device.createComputePipelineUnique(cache, compute_pipeline_ci);
        }
        if (created.result == vk::Result::ePipelineCompileRequired &&
            (flags & vk::PipelineCreateFlagBits::eFailOnPipelineCompileRequired)) {
            return {};
        }
        ASSERT_MSG(created.result == vk::Result::eSuccess, "Failed to create compute pipeline: {}",
                   vk::to_string(created.result));
        SetObjectName(device, *created.value, "Compute Pipeline {}", debug_str);
        return std::move(created.value);
    };

    // tlg: a dispatch waits on a pipeline hit in game, and compute work cannot be skipped.
    // Built on the compiler threads while the GPU thread continues; TLG_COMPUTE_ASYNC_BUILD=0 disables.
    static const bool async_build = [] {
        const char* env = std::getenv("TLG_COMPUTE_ASYNC_BUILD");
        return !(env && env[0] == '0');
    }();
    if (builder && !preloading && async_build &&
        instance.IsPipelineCreationCacheControlSupported()) {
        pipeline = create(pipeline_cache,
                          vk::PipelineCreateFlagBits::eFailOnPipelineCompileRequired);
        if (pipeline) {
            return;
        }
        auto state = std::make_shared<Build>();
        const auto caches = builder->caches;
        const bool deferred_bind = scheduler.RecordsOnThread();
        const bool queued = builder->compiler->Submit(
            [state, create, caches, deferred_bind, debug_str] {
                const auto start = std::chrono::steady_clock::now();
                auto built = create(*caches[AsyncCompiler::WorkerIndex()], {});
                LOG_INFO(Render_Vulkan,
                         "tlg: compute pipeline {} built on a compiler thread in {:.1f} ms{}",
                         debug_str,
                         std::chrono::duration<double, std::milli>(
                             std::chrono::steady_clock::now() - start)
                             .count(),
                         deferred_bind ? "" : " (replaces the unoptimized one)");
                {
                    std::scoped_lock lock{state->mutex};
                    if (deferred_bind) {
                        state->handle.store(static_cast<VkPipeline>(*built),
                                            std::memory_order_release);
                    }
                    state->result = std::move(built);
                    state->done.store(true, std::memory_order_release);
                }
                state->cv.notify_all();
            },
            deferred_bind);
        if (queued) {
            build = std::move(state);
            if (!deferred_bind) {
                pipeline = create(pipeline_cache, vk::PipelineCreateFlagBits::eDisableOptimization);
                build->handle.store(static_cast<VkPipeline>(*pipeline), std::memory_order_release);
                optimized_pending = true;
            }
            return;
        }
    }
    pipeline = create(pipeline_cache, {});
}

ComputePipeline::~ComputePipeline() {
    // A build still queued uses the layout and module.
    if (build) {
        std::unique_lock lock{build->mutex};
        build->cv.wait(lock, [this] { return build->done.load(std::memory_order_acquire); });
    }
}

void ComputePipeline::SwapInOptimized() {
    if (!optimized_pending || !build->done.load(std::memory_order_acquire)) {
        return;
    }
    optimized_pending = false;
    vk::UniquePipeline old = std::move(pipeline);
    pipeline = std::move(build->result);
    build->handle.store(static_cast<VkPipeline>(*pipeline), std::memory_order_release);
    scheduler.DeferOperation([scheduler = &scheduler, old = std::move(old)]() mutable {
        scheduler->DeferOperation([old = std::move(old)]() mutable { old.reset(); });
    });
}

} // namespace Vulkan
