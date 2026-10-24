cmake_minimum_required(VERSION 3.20)
project(shipmb_vision_project VERSION 0.6.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# llama.cpp b11846 (commit 1a24df163920a4744a95373d178d790b72a9bb2f).
# Fetched at configure time. CPU on every platform. Metal on Apple.
# CUDA and Vulkan stay off. The five-file patch under patches/ is the
# difference between that tag and the tree this library was written against.
set(LLAMA_BUILD_NUMBER 11846 CACHE STRING "" FORCE)
set(LLAMA_BUILD_COMMIT "1a24df163920a4744a95373d178d790b72a9bb2f" CACHE STRING "" FORCE)
set(GGML_BUILD_COMMIT "1a24df16" CACHE STRING "" FORCE)
set(LLAMA_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_APP OFF CACHE BOOL "" FORCE)
set(LLAMA_OPENSSL OFF CACHE BOOL "" FORCE)
set(LLAMA_LLGUIDANCE OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_MTMD ON CACHE BOOL "" FORCE)
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(GGML_CUDA OFF CACHE BOOL "" FORCE)
set(GGML_MUSA OFF CACHE BOOL "" FORCE)
set(GGML_HIP OFF CACHE BOOL "" FORCE)
set(GGML_VULKAN OFF CACHE BOOL "" FORCE)
set(GGML_WEBGPU OFF CACHE BOOL "" FORCE)
set(GGML_OPENCL OFF CACHE BOOL "" FORCE)
set(GGML_SYCL OFF CACHE BOOL "" FORCE)
set(GGML_RPC OFF CACHE BOOL "" FORCE)
set(GGML_BLAS OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)
set(GGML_BACKEND_DL OFF CACHE BOOL "" FORCE)
set(MTMD_VIDEO OFF CACHE BOOL "" FORCE)
set(LLAMA_SUBPROCESS OFF CACHE BOOL "" FORCE)
if(APPLE)
  set(GGML_METAL ON CACHE BOOL "" FORCE)
else()
  set(GGML_METAL OFF CACHE BOOL "" FORCE)
endif()
option(SHIPMB_VISION_QUANTIZE "Also build llama-quantize to reproduce the q8_0 mmproj" OFF)
if(SHIPMB_VISION_QUANTIZE)
  set(LLAMA_BUILD_COMMON ON CACHE BOOL "" FORCE)
else()
  set(LLAMA_BUILD_COMMON OFF CACHE BOOL "" FORCE)
endif()

set(SHIPMB_LLAMA_COMMIT "1a24df163920a4744a95373d178d790b72a9bb2f")
set(SHIPMB_LLAMA_TAG "b11846")
include(FetchContent)
FetchContent_Declare(
  llamacpp
  GIT_REPOSITORY https://github.com/ggml-org/llama.cpp.git
  GIT_TAG ${SHIPMB_LLAMA_TAG}
  GIT_SHALLOW TRUE)
FetchContent_GetProperties(llamacpp)
if(NOT llamacpp_POPULATED)
  FetchContent_Populate(llamacpp)
endif()
execute_process(
  COMMAND git -C "${llamacpp_SOURCE_DIR}" rev-parse HEAD
  OUTPUT_VARIABLE SHIPMB_LLAMA_FETCHED
  OUTPUT_STRIP_TRAILING_WHITESPACE
  COMMAND_ERROR_IS_FATAL ANY)
if(NOT SHIPMB_LLAMA_FETCHED STREQUAL SHIPMB_LLAMA_COMMIT)
  message(FATAL_ERROR "Fetched llama.cpp ${SHIPMB_LLAMA_FETCHED}, expected ${SHIPMB_LLAMA_COMMIT}")
endif()
set(SHIPMB_LLAMA_PATCH_STAMP "${llamacpp_BINARY_DIR}/shipmb-b11846.patch-applied")
if(NOT EXISTS "${SHIPMB_LLAMA_PATCH_STAMP}")
  execute_process(
    COMMAND git -C "${llamacpp_SOURCE_DIR}" apply --whitespace=nowarn
            "${CMAKE_CURRENT_SOURCE_DIR}/patches/llama.cpp-b11846-shipmb.patch"
    COMMAND_ERROR_IS_FATAL ANY)
  file(WRITE "${SHIPMB_LLAMA_PATCH_STAMP}" "${SHIPMB_LLAMA_COMMIT}\n")
endif()
add_subdirectory("${llamacpp_SOURCE_DIR}" "${llamacpp_BINARY_DIR}")

add_library(shipmb_vision SHARED
  src/shipmb_vision.cpp
  src/image_rgb.cpp
  src/sha256.cpp)
target_compile_definitions(shipmb_vision PRIVATE SMB_VISION_BUILD)
if(APPLE)
  target_compile_definitions(shipmb_vision PRIVATE SMB_VISION_HAS_METAL=1)
endif()
target_include_directories(shipmb_vision
  PUBLIC include
  PRIVATE src
          "${CMAKE_CURRENT_SOURCE_DIR}/vendor"
          "${llamacpp_SOURCE_DIR}/vendor/stb")
target_link_libraries(shipmb_vision PRIVATE mtmd llama)
target_compile_features(shipmb_vision PRIVATE cxx_std_17)
if(MSVC)
  target_compile_options(shipmb_vision PRIVATE /EHsc /utf-8)
  # The process main thread takes its reserve from the executable, not this DLL.
  target_link_options(shipmb_vision PRIVATE "/STACK:8388608")
else()
  target_compile_options(shipmb_vision PRIVATE -Wall -Wextra -Wno-unused-function)
endif()
if(UNIX AND NOT APPLE)
  target_link_libraries(shipmb_vision PRIVATE dl pthread)
endif()
set_target_properties(shipmb_vision PROPERTIES
  OUTPUT_NAME shipmb_vision
  POSITION_INDEPENDENT_CODE ON)

if(SHIPMB_VISION_QUANTIZE)
  add_subdirectory("${llamacpp_SOURCE_DIR}/tools/quantize" "${llamacpp_BINARY_DIR}/tools/quantize")
endif()

include(CTest)
if(BUILD_TESTING)
  add_executable(shipmb_vision_smoke tests/smoke.c)
  target_link_libraries(shipmb_vision_smoke PRIVATE shipmb_vision)
  add_test(NAME shipmb_vision_smoke COMMAND shipmb_vision_smoke)
  set_tests_properties(shipmb_vision_smoke PROPERTIES TIMEOUT 120)

  add_executable(shipmb_vision_sha_test tests/sha_test.cpp)
  target_sources(shipmb_vision_sha_test PRIVATE src/sha256.cpp)
  target_include_directories(shipmb_vision_sha_test PRIVATE src)
  add_test(NAME shipmb_vision_sha_test COMMAND shipmb_vision_sha_test)

  add_executable(shipmb_vision_bench tests/bench.c)
  target_link_libraries(shipmb_vision_bench PRIVATE shipmb_vision)

  add_executable(shipmb_vision_parity tests/parity.c)
  target_link_libraries(shipmb_vision_parity PRIVATE shipmb_vision)
  add_test(NAME shipmb_vision_parity COMMAND shipmb_vision_parity
    "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/minicpmv46-tiny")
  set_tests_properties(shipmb_vision_parity PROPERTIES TIMEOUT 180)
  if(MSVC)
    foreach(vision_tool shipmb_vision_smoke shipmb_vision_sha_test shipmb_vision_bench shipmb_vision_parity)
      target_link_options(${vision_tool} PRIVATE "/STACK:8388608")
    endforeach()
  endif()
endif()
