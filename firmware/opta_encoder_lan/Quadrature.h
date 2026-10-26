#pragma once
#include <stdint.h>

// Decodifica x4: ogni transizione A/B valida equivale a un conteggio.
struct Quadrature {
  int64_t position = 0;
  uint64_t total = 0;
  uint32_t edgesA = 0;
  uint32_t edgesB = 0;
  uint32_t invalid = 0;
  uint8_t previous = 0;

  void begin(uint8_t state) volatile { previous = state & 3; }

  void observe(uint8_t state) volatile {
    static constexpr int8_t delta[16] = {
      0, 1, -1, 0, -1, 0, 0, 1,
      1, 0, 0, -1, 0, -1, 1, 0
    };
    state &= 3;
    const uint8_t changed = previous ^ state;
    if (!changed) return;
    if (changed & 2) ++edgesA;
    if (changed & 1) ++edgesB;
    if (changed == 3) {
      // Mancano fronti o c'e' rumore: non inventare una direzione.
      ++invalid;
    } else {
      position += delta[(previous << 2) | state];
      ++total;
    }
    previous = state;
  }
};
