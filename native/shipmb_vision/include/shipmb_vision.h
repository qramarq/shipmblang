#ifndef SHIPMB_VISION_H
#define SHIPMB_VISION_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(_WIN32)
#  if defined(SMB_VISION_BUILD)
#    define SMB_VISION_API __declspec(dllexport)
#  else
#    define SMB_VISION_API __declspec(dllimport)
#  endif
#else
#  define SMB_VISION_API __attribute__((visibility("default")))
#endif

/* Token piece callback. `piece` is not necessarily a full UTF-8 scalar; it is
   the raw bytes llama.cpp emitted for one token, NUL-terminated. The callback
   must not re-enter the engine. */
typedef void (*smb_vision_token_fn)(const char *piece, void *user);

/* Initialize backends and return a JSON object naming them. The pointer is
   invalidated by the next call on this thread. */
SMB_VISION_API const char *smb_vision_runtime(void);

/* Load the resident engine. `config_json` may be NULL. On failure returns
   NULL and smb_vision_last_error() explains why, including the
   `shipmblang setup --vision` hint when weights are missing. */
SMB_VISION_API void *smb_vision_create(const char *config_json);

/* Recognize `image_path`. `options_json` may be NULL and may set
   "detailed" (bool) and "max_tokens" (int). Returns a JSON object. The
   pointer is invalidated by the next call on this thread. */
SMB_VISION_API const char *smb_vision_query(void *engine, const char *image_path, const char *question, const char *options_json);

/* Same as smb_vision_query, invoking `on_token` for each generated piece. */
SMB_VISION_API const char *smb_vision_query_stream(void *engine, const char *image_path, const char *question, const char *options_json, smb_vision_token_fn on_token, void *user);

SMB_VISION_API void smb_vision_free(void *engine);

SMB_VISION_API const char *smb_vision_last_error(void);

#ifdef __cplusplus
}
#endif

#endif
