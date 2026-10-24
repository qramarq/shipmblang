#include "shipmb_vision.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int fail(const char *message) {
    fprintf(stderr, "parity: %s\n", message);
    return 1;
}

static char *read_file(const char *path) {
    FILE *file = fopen(path, "rb");
    if (!file) return NULL;
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return NULL;
    }
    long size = ftell(file);
    if (size < 0 || size > 1000000) {
        fclose(file);
        return NULL;
    }
    if (fseek(file, 0, SEEK_SET) != 0) {
        fclose(file);
        return NULL;
    }
    char *text = (char *)malloc((size_t)size + 1);
    if (!text) {
        fclose(file);
        return NULL;
    }
    if (fread(text, 1, (size_t)size, file) != (size_t)size) {
        free(text);
        fclose(file);
        return NULL;
    }
    text[size] = '\0';
    fclose(file);
    return text;
}

static const char *json_value(const char *json, const char *key) {
    char pattern[64];
    snprintf(pattern, sizeof pattern, "\"%s\"", key);
    const char *found = strstr(json, pattern);
    if (!found) return NULL;
    found += strlen(pattern);
    while (*found == ' ' || *found == '\n' || *found == '\r' || *found == '\t') ++found;
    if (*found != ':') return NULL;
    ++found;
    while (*found == ' ' || *found == '\n' || *found == '\r' || *found == '\t') ++found;
    return found;
}

static int json_int(const char *json, const char *key, int *out) {
    const char *found = json_value(json, key);
    if (!found) return 0;
    return sscanf(found, "%d", out) == 1;
}

static int json_string(const char *json, const char *key, char *out, size_t out_size) {
    const char *found = json_value(json, key);
    if (!found || *found != '"') return 0;
    ++found;
    size_t n = 0;
    while (*found && *found != '"' && n + 1 < out_size) out[n++] = *found++;
    if (*found != '"') return 0;
    out[n] = '\0';
    return 1;
}

static void slash(char *path) {
    for (char *p = path; *p; ++p) {
        if (*p == '\\') *p = '/';
    }
}

int main(int argc, char **argv) {
    setvbuf(stderr, NULL, _IONBF, 0);
    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc != 2) return fail("usage: shipmb_vision_parity <fixture-dir>");
    char golden_path[1024];
    char model_path[1024];
    char mmproj_path[1024];
    char image_path[1024];
    snprintf(golden_path, sizeof golden_path, "%s/golden.json", argv[1]);
    snprintf(model_path, sizeof model_path, "%s/model.gguf", argv[1]);
    snprintf(mmproj_path, sizeof mmproj_path, "%s/mmproj.gguf", argv[1]);
    snprintf(image_path, sizeof image_path, "%s/sample.png", argv[1]);
    slash(model_path);
    slash(mmproj_path);
    slash(image_path);

    char *golden = read_file(golden_path);
    if (!golden) return fail("could not read golden.json");
    char expect_text[128];
    int expect_tokens = -1;
    int max_tokens = 1;
    if (!json_string(golden, "text", expect_text, sizeof expect_text)) {
        free(golden);
        return fail("golden.json has no text");
    }
    if (!json_int(golden, "image_tokens", &expect_tokens)) {
        free(golden);
        return fail("golden.json has no image_tokens");
    }
    json_int(golden, "max_tokens", &max_tokens);
    free(golden);

    char config[4096];
    snprintf(config, sizeof config,
             "{\"model_path\":\"%s\",\"mmproj_path\":\"%s\",\"n_threads\":1,\"n_ctx\":2048,"
             "\"max_tokens\":%d,\"flash_attn\":false,\"detailed\":true,\"use_gpu\":false,\"warmup\":true}",
             model_path, mmproj_path, max_tokens);
    fprintf(stderr, "parity: loading\n");
    void *engine = smb_vision_create(config);
    if (!engine) {
        fprintf(stderr, "create: %s\n", smb_vision_last_error());
        return fail("fixture engine failed to load");
    }
    char options[128];
    snprintf(options, sizeof options, "{\"detailed\":true,\"max_tokens\":%d}", max_tokens);
    fprintf(stderr, "parity: querying\n");
    const char *raw = smb_vision_query(engine, image_path, "cat", options);
    if (!raw || !strstr(raw, "\"ok\":true")) {
        fprintf(stderr, "query: %s\n", raw ? raw : smb_vision_last_error());
        smb_vision_free(engine);
        return fail("fixture query failed");
    }
    char got_text[128];
    int got_tokens = -1;
    if (!json_string(raw, "text", got_text, sizeof got_text) || !json_int(raw, "image_tokens", &got_tokens)) {
        fprintf(stderr, "query: %s\n", raw);
        smb_vision_free(engine);
        return fail("fixture query did not report text and image_tokens");
    }
    int mismatch = strcmp(got_text, expect_text) != 0 || got_tokens != expect_tokens;
    if (mismatch) {
        fprintf(stderr, "expected text %s (%d image tokens), got %s (%d)\n%s\n",
                expect_text, expect_tokens, got_text, got_tokens, raw);
        smb_vision_free(engine);
        return fail("greedy tokens diverged from golden.json");
    }
    printf("parity: %s image_tokens=%d %s\n", got_text, got_tokens, raw);
    smb_vision_free(engine);
    return 0;
}
