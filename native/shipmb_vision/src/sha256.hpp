#ifndef SHIPMB_SHA256_HPP
#define SHIPMB_SHA256_HPP

#include <stddef.h>
#include <stdint.h>

#include <array>
#include <string>

/* Streaming SHA-256. hex() returns 64 lowercase hex digits. */
struct Sha256 {
    Sha256();
    void update(const void *data, size_t len);
    std::array<uint8_t, 32> digest() const;
    std::string hex() const;

private:
    uint32_t state[8];
    uint64_t bits;
    uint8_t buffer[64];
    size_t used;
};

std::string sha256_file(const std::string &path);

#endif
