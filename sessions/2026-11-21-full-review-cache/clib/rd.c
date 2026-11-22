#include <stdio.h>
int first_char(const char *p) { FILE *f = fopen(p, "r"); if (!f) return -1; int c = fgetc(f); fclose(f); return c; }
