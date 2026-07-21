#include "cobs.h"

uint8_t cobs_decode(const uint8_t* src, uint8_t src_len,
                    uint8_t* dst, uint8_t dst_max) {
    uint8_t out = 0;
    uint8_t idx = 0;

    while (idx < src_len) {
        uint8_t code = src[idx++];
        if (code == 0) return 0;   // 0x00 invalid inside COBS frame

        for (uint8_t i = 1; i < code; i++) {
            if (idx >= src_len || out >= dst_max) return 0;
            dst[out++] = src[idx++];
        }
        if (idx < src_len) {
            if (out >= dst_max) return 0;
            dst[out++] = 0x00;
        }
    }
    return out;
}

uint8_t cobs_encode(const uint8_t* src, uint8_t src_len, uint8_t* dst) {
    uint8_t code_idx = 0;
    uint8_t code     = 1;
    uint8_t out_idx  = 1;

    for (uint8_t i = 0; i < src_len; i++) {
        if (src[i] != 0x00) {
            dst[out_idx++] = src[i];
            code++;
            if (code == 0xFF) {
                dst[code_idx] = code;
                code_idx = out_idx;
                dst[out_idx++] = 0x01;
                code = 1;
            }
        } else {
            dst[code_idx] = code;
            code_idx = out_idx;
            dst[out_idx++] = 0x01;
            code = 1;
        }
    }
    dst[code_idx] = code;
    return out_idx;
}
