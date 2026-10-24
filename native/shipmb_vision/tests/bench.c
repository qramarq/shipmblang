#include "shipmb_vision.h"

#include <stdio.h>
#include <stdlib.h>

/* Warm-recognition timing. usage: shipmb_vision_bench config.json image question iters */
int main(int argc, char **argv) {
    if (argc < 5) {
        fprintf(stderr, "usage: %s config.json image question iters\n", argv[0]);
        return 2;
    }
    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        perror(argv[1]);
        return 2;
    }
    if (fseek(f, 0, SEEK_END) != 0) return 2;
    long n = ftell(f);
    if (n < 0 || n > 1000000) return 2;
    rewind(f);
    char *config = (char *)malloc((size_t)n + 1);
    if (!config || fread(config, 1, (size_t)n, f) != (size_t)n) return 2;
    config[n] = 0;
    fclose(f);
    void *engine = smb_vision_create(config);
    free(config);
    if (!engine) {
        fprintf(stderr, "%s\n", smb_vision_last_error());
        return 1;
    }
    int iters = atoi(argv[4]);
    if (iters < 1) iters = 1;
    for (int i = 0; i < iters; ++i) {
        const char *result = smb_vision_query(engine, argv[2], argv[3], NULL);
        printf("%s\n", result ? result : "{\"ok\":false,\"error\":\"null result\"}");
        fflush(stdout);
    }
    smb_vision_free(engine);
    return 0;
}
