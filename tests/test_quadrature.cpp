#include <cassert>
#include <initializer_list>
#include "../firmware/opta_encoder_reader/Quadrature.h"

int main() {
  volatile Quadrature encoder;
  encoder.begin(0);
  // Un giro da 600 periodi A/B deve produrre 2400 conteggi x4.
  for (unsigned i = 0; i < 600; ++i)
    for (uint8_t state : {1, 3, 2, 0}) encoder.observe(state);
  assert(encoder.position == 2400 && encoder.total == 2400);
  assert(encoder.edgesA == 1200 && encoder.edgesB == 1200);
  for (unsigned i = 0; i < 600; ++i)
    for (uint8_t state : {2, 3, 1, 0}) encoder.observe(state);
  assert(encoder.position == 0 && encoder.total == 4800);
  encoder.observe(0);
  assert(encoder.total == 4800);
  encoder.observe(3);  // salto illegale: nessun conteggio attribuito
  assert(encoder.invalid == 1 && encoder.position == 0 && encoder.total == 4800);
  // Posizione negativa e gestione del confine a 32 bit.
  encoder.begin(0);
  for (uint8_t state : {2, 3, 1, 0}) encoder.observe(state);
  assert(encoder.position == -4);
  encoder.position = INT64_C(4294967296);
  encoder.total = UINT64_C(4294967296);
  for (uint8_t state : {1, 3, 2, 0}) encoder.observe(state);
  assert(encoder.position == INT64_C(4294967300));
  assert(encoder.total == UINT64_C(4294967300));
}
