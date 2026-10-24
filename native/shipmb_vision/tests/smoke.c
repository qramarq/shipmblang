#include "shipmb_vision.h"

#include <stdio.h>
#include <string.h>

static int fail(const char *message) {
    fprintf(stderr, "smoke: %s\n", message);
    return 1;
}

int main(void) {
    const char *runtime = smb_vision_runtime();
    if (!runtime || !strstr(runtime, "CPU")) {
        fprintf(stderr, "runtime: %s\n", runtime ? runtime : "(null)");
        return fail("runtime did not report a CPU backend");
    }
    void *engine = smb_vision_create("{\"model_path\":\"/no/such/shipmb-vision-model.gguf\",\"mmproj_path\":\"/no/such/shipmb-vision-mmproj.gguf\"}");
    if (engine) return fail("create accepted missing weights");
    const char *err = smb_vision_last_error();
    if (!err || !strstr(err, "shipmblang setup --vision")) {
        fprintf(stderr, "error: %s\n", err ? err : "(null)");
        return fail("missing-weights diagnostic is wrong");
    }
    const char *query = smb_vision_query(NULL, "photo.jpg", "what is this?", NULL);
    if (!query || !strstr(query, "\"ok\":false")) return fail("null engine query was not an error");
    const char *stream = smb_vision_query_stream(NULL, "photo.jpg", "what is this?", NULL, NULL, NULL);
    if (!stream || !strstr(stream, "\"ok\":false")) return fail("null engine stream was not an error");
    smb_vision_free(NULL);
    printf("%s\n", runtime);
    return 0;
}
