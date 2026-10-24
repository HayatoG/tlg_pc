// SPDX-FileCopyrightText: Copyright 2026 IFreemz (shadps4_dlss bridge), tlg contributors
// SPDX-License-Identifier: MIT
//
// C interface between tlg and tlg_dlss.dll. The port contains no NVIDIA code: it loads the
// bridge at run time when it is present (next to tlg-probe.exe, with nvngx_dlss.dll) and keeps
// its other upscalers when it is absent. Adapted from IFreemz/shadPS4-Bloodborne-DLSS-FSR.

#pragma once

#include <stdint.h>
#include <vulkan/vulkan.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TLG_DLSS_BRIDGE_ABI 1

typedef void (*TlgDlssLogFn)(int warning, const char* message);

typedef struct TlgDlssImage {
    VkImage image;
    VkImageView view;
    VkImageSubresourceRange range;
    VkFormat format;
    uint32_t width;
    uint32_t height;
} TlgDlssImage;

typedef struct TlgDlssFeature {
    uint32_t input_width;
    uint32_t input_height;
    uint32_t output_width;
    uint32_t output_height;
    int32_t quality; // 0 DLAA, 1 Quality, 2 Balanced, 3 Performance, 4 Ultra Performance
    int32_t depth_inverted;
    uint32_t preset; // NVSDK_NGX_DLSS_Hint_Render_Preset value, 0 = driver default
    int32_t hdr;     // 1: linear HDR colour with automatic exposure, 2: without, 0: tonemapped colour
} TlgDlssFeature;

typedef struct TlgDlssEvaluate {
    TlgDlssImage color;  // sampled
    TlgDlssImage depth;  // sampled, hardware depth
    TlgDlssImage motion; // sampled, render-resolution pixels, current to previous
    TlgDlssImage output; // storage, general layout
    float jitter_x;
    float jitter_y;
    int32_t reset;
    float frame_ms;
    float sharpness; // 0..1; 0 leaves the output unsharpened
} TlgDlssEvaluate;

typedef struct TlgDlssApi {
    uint32_t abi;
    // UTF-16 paths: the directory with nvngx_dlss.dll, and a writable data directory.
    int32_t (*Configure)(const wchar_t* dll_directory, const wchar_t* data_directory,
                         TlgDlssLogFn log);
    // Vulkan extensions NGX needs. The arrays stay valid until Shutdown.
    int32_t (*InstanceExtensions)(uint32_t* count, const VkExtensionProperties** extensions);
    int32_t (*DeviceExtensions)(VkInstance instance, VkPhysicalDevice physical, uint32_t* count,
                                const VkExtensionProperties** extensions);
    int32_t (*Initialize)(VkInstance instance, VkPhysicalDevice physical, VkDevice device,
                          PFN_vkGetInstanceProcAddr get_instance_proc,
                          PFN_vkGetDeviceProcAddr get_device_proc);
    int32_t (*CreateFeature)(VkCommandBuffer command, const TlgDlssFeature* feature);
    int32_t (*Evaluate)(VkCommandBuffer command, const TlgDlssEvaluate* evaluate);
    // The caller must have waited for the GPU work that used the feature.
    void (*ReleaseFeature)(void);
    void (*Shutdown)(void);
} TlgDlssApi;

typedef const TlgDlssApi* (*TlgDlssGetApiFn)(void);

#ifdef __cplusplus
}
#endif
