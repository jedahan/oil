#include <string>
#include <stdio.h>
#include <stdlib.h>

#include "opcode.h"

int main(int argc, char **argv) {
  if (argc == 0) {
    printf("Expected filename\n");
    return 1;
  }
  FILE *f = fopen(argv[1], "rb");
  if (!f) {
    printf("Error opening %s", argv[1]);
    return 1;
  }
  fseek(f, 0, SEEK_END);
  size_t num_bytes = ftell(f);
  fseek(f, 0, SEEK_SET);  //same as rewind(f);

  uint8_t* image = static_cast<uint8_t*>(malloc(num_bytes + 1));
  fread(image, num_bytes, 1, f);
  fclose(f);

  image[num_bytes] = 0;
  printf("Read %zu bytes\n", num_bytes);
}
