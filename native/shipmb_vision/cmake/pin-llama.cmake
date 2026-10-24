# Verify the fetched llama.cpp commit and apply the shipmb patch once.
# FetchContent runs this with the working directory set to the source tree.
# EXPECTED and PATCH_FILE are passed as -D arguments. CMake paths use forward
# slashes, including on Windows, so the arguments are not eaten as escapes.
if(NOT DEFINED EXPECTED OR NOT DEFINED PATCH_FILE)
  message(FATAL_ERROR "pin-llama.cmake requires EXPECTED and PATCH_FILE")
endif()
if(NOT EXISTS "${PATCH_FILE}")
  message(FATAL_ERROR "llama.cpp patch was not found: ${PATCH_FILE}")
endif()

execute_process(
  COMMAND git rev-parse HEAD
  OUTPUT_VARIABLE HEAD
  OUTPUT_STRIP_TRAILING_WHITESPACE
  COMMAND_ERROR_IS_FATAL ANY)
if(NOT HEAD STREQUAL EXPECTED)
  message(FATAL_ERROR "Fetched llama.cpp ${HEAD}, expected ${EXPECTED}")
endif()

execute_process(
  COMMAND git apply --check --whitespace=nowarn "${PATCH_FILE}"
  RESULT_VARIABLE CHECK)
if(CHECK EQUAL 0)
  message(STATUS "Applying ${PATCH_FILE}")
  execute_process(
    COMMAND git apply --whitespace=nowarn "${PATCH_FILE}"
    COMMAND_ERROR_IS_FATAL ANY)
else()
  execute_process(
    COMMAND git apply --reverse --check --whitespace=nowarn "${PATCH_FILE}"
    RESULT_VARIABLE REVERSE)
  if(NOT REVERSE EQUAL 0)
    message(FATAL_ERROR
      "llama.cpp is neither pristine nor already carrying ${PATCH_FILE}. "
      "Delete the build directory and configure again.")
  endif()
endif()
