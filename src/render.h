#ifndef STAR_SEARCH_RENDER_H
#define STAR_SEARCH_RENDER_H

#include "star_params.h"

#include <stdbool.h>
#include <stdint.h>

#define RENDER_MIN_SIZE 16
#define RENDER_MAX_SIZE 4096
#define RENDER_DEFAULT_SIZE 512

/* Evaluate src/shaders/star.frag on the CPU for every pixel of a width x height
 * image. rgb receives width*height*3 bytes, top row first (sRGB, 8-bit). */
void render_star(const star_render_params *params, int width, int height, uint8_t *rgb);

/* Encode rgb as an 8-bit RGB PNG at path, creating parent directories.
 * Returns false (errno set where applicable) on failure. */
bool write_png(const char *path, int width, int height, const uint8_t *rgb);

/* Create every missing directory component of path's parent (mkdir -p dirname). */
bool make_parent_directories(const char *path);

#endif
