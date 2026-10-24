#include "image_rgb.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define STB_IMAGE_STATIC
#define STB_IMAGE_IMPLEMENTATION
#ifdef _WIN32
#define STBI_WINDOWS_UTF8
#endif
#define STBI_NO_PSD
#define STBI_NO_HDR
#define STBI_NO_PIC
#define STBI_NO_PNM
#include "stb_image.h"

static void set_err(char *err, size_t err_len, const char *message) {
    if (!err || err_len == 0) return;
    snprintf(err, err_len, "%s", message);
}

int smb_rgb_decode_file(const char *path, smb_rgb *out, char *err, size_t err_len) {
    if (!out) {
        set_err(err, err_len, "Image output is missing.");
        return 1;
    }
    out->data = NULL;
    out->width = 0;
    out->height = 0;
    int w = 0, h = 0, n = 0;
    unsigned char *decoded = stbi_load(path, &w, &h, &n, 3);
    if (!decoded || w <= 0 || h <= 0) {
        if (decoded) stbi_image_free(decoded);
        set_err(err, err_len, "The image could not be decoded. Use PNG, JPEG, GIF, or BMP.");
        return 1;
    }
    if ((long long)w * (long long)h > 40000000LL) {
        stbi_image_free(decoded);
        set_err(err, err_len, "The image is larger than 40 megapixels.");
        return 1;
    }
    out->data = decoded;
    out->width = w;
    out->height = h;
    return 0;
}

int smb_rgb_resize_long_side(const smb_rgb *src, int long_side, smb_rgb *dst, char *err, size_t err_len) {
    if (!src || !src->data || !dst || long_side <= 0) {
        set_err(err, err_len, "Image resize input is missing.");
        return 1;
    }
    dst->data = NULL;
    dst->width = 0;
    dst->height = 0;
    const int sw = src->width;
    const int sh = src->height;
    int dw = sw;
    int dh = sh;
    if (sw >= sh) {
        dw = long_side;
        dh = (int)llround((double)sh * (double)long_side / (double)sw);
        if (dh < 1) dh = 1;
    } else {
        dh = long_side;
        dw = (int)llround((double)sw * (double)long_side / (double)sh);
        if (dw < 1) dw = 1;
    }
    unsigned char *out = (unsigned char *)malloc((size_t)dw * (size_t)dh * 3);
    if (!out) {
        set_err(err, err_len, "Out of memory while resizing the image.");
        return 1;
    }
    if (dw == sw && dh == sh) {
        memcpy(out, src->data, (size_t)dw * (size_t)dh * 3);
    } else {
        for (int y = 0; y < dh; ++y) {
            float fy = ((float)y + 0.5f) * (float)sh / (float)dh - 0.5f;
            int y0 = (int)floorf(fy);
            float wy = fy - (float)y0;
            if (y0 < 0) { y0 = 0; wy = 0.f; }
            int y1 = y0 + 1;
            if (y1 >= sh) y1 = sh - 1;
            if (y0 >= sh) y0 = sh - 1;
            for (int x = 0; x < dw; ++x) {
                float fx = ((float)x + 0.5f) * (float)sw / (float)dw - 0.5f;
                int x0 = (int)floorf(fx);
                float wx = fx - (float)x0;
                if (x0 < 0) { x0 = 0; wx = 0.f; }
                int x1 = x0 + 1;
                if (x1 >= sw) x1 = sw - 1;
                if (x0 >= sw) x0 = sw - 1;
                for (int c = 0; c < 3; ++c) {
                    float v =
                        src->data[((size_t)y0 * sw + x0) * 3 + c] * (1.f - wy) * (1.f - wx) +
                        src->data[((size_t)y0 * sw + x1) * 3 + c] * (1.f - wy) * wx +
                        src->data[((size_t)y1 * sw + x0) * 3 + c] * wy * (1.f - wx) +
                        src->data[((size_t)y1 * sw + x1) * 3 + c] * wy * wx;
                    int iv = (int)(v + 0.5f);
                    if (iv < 0) iv = 0;
                    if (iv > 255) iv = 255;
                    out[((size_t)y * dw + x) * 3 + c] = (unsigned char)iv;
                }
            }
        }
    }
    dst->data = out;
    dst->width = dw;
    dst->height = dh;
    return 0;
}

void smb_rgb_free(smb_rgb *image) {
    if (!image) return;
    free(image->data);
    image->data = NULL;
    image->width = 0;
    image->height = 0;
}
