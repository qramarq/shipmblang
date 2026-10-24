#ifndef SHIPMB_IMAGE_RGB_H
#define SHIPMB_IMAGE_RGB_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct smb_rgb {
    unsigned char *data;
    int width;
    int height;
} smb_rgb;

/* Decode the first frame of a stb-supported image (png, jpeg, gif, bmp, ...)
   into tightly packed RGB. Returns 0 on success. */
int smb_rgb_decode_file(const char *path, smb_rgb *out, char *err, size_t err_len);

/* Longest side becomes `long_side` pixels. Aspect ratio is preserved and the
   chosen side is exact. `src` and `dst` may not alias. */
int smb_rgb_resize_long_side(const smb_rgb *src, int long_side, smb_rgb *dst, char *err, size_t err_len);

void smb_rgb_free(smb_rgb *image);

#ifdef __cplusplus
}
#endif

#endif
