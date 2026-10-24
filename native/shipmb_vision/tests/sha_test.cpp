#include "sha256.hpp"

#include <stdio.h>
#include <string>

int main() {
    Sha256 h;
    const char *abc = "abc";
    h.update(abc, 3);
    const std::string hex = h.hex();
    const char *expect = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
    if (hex != expect) {
        fprintf(stderr, "sha256(abc) = %s\n", hex.c_str());
        return 1;
    }
    Sha256 empty;
    if (empty.hex() != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855") {
        fprintf(stderr, "sha256() = %s\n", empty.hex().c_str());
        return 1;
    }
    return 0;
}
