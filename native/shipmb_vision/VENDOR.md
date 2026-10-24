# llama.cpp

This directory does not contain llama.cpp. Configure fetches it.

| | |
| --- | --- |
| Upstream | https://github.com/ggml-org/llama.cpp |
| Tag | `b11846` |
| Commit | `1a24df163920a4744a95373d178d790b72a9bb2f` |
| Git tree | `9c30347a586081a77fe87b3fa9ef02dda8221674` |
| Method | CMake `FetchContent`, `GIT_REPOSITORY` + `GIT_TAG b11846` + `GIT_SHALLOW TRUE` |
| License | MIT, copied at `licenses/llama.cpp-MIT.txt`. The clone's own `LICENSE` is the same text. |

`patches/llama.cpp-b11846-shipmb.patch` is the whole delta from that tag to the sources this library builds against. Five files:

- `cmake/build-info.cmake` and `ggml/CMakeLists.txt` skip the git probe when the commit is already pinned, so a checkout inside another git repo does not inherit that repo's revision.
- `ggml/src/ggml.c` flushes stderr around an abort.
- `ggml/src/ggml-cpu/ggml-cpu.c` reserves an 8 MiB Windows thread stack.
- `conversion/minicpm.py` is the converter delta. It is not linked into `libshipmb_vision.so`.

`vendor/json.hpp` is nlohmann/json 3.11.3 (MIT, `vendor/JSON-LICENSE.MIT`). It is not the copy inside llama.cpp. `src/image_rgb.cpp` includes `stb_image.h` from the fetched llama.cpp tree (`vendor/stb`).

Build with the commands in `BUILD.md`. CPU code is compiled on every platform. Metal is on for Apple. CUDA and Vulkan are forced off.
