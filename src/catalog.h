#ifndef STAR_SEARCH_CATALOG_H
#define STAR_SEARCH_CATALOG_H

#include "result.h"

#include <stdbool.h>
#include <stdint.h>

/* v1.0 backend: the starsearch.online JSON API (one source of truth with the
 * website). A future v2.0 may add an optional local DuckDB backend behind this
 * same interface; callers only see catalog_result tables. */
typedef struct {
    void *http;     /* backend handle (CURL easy handle) */
    char *base_url; /* API base URL without a trailing slash */
} catalog;

/* `source` is the API base URL (e.g. https://starsearch.online). */
bool catalog_open(catalog *catalogue, const char *source);
void catalog_close(catalog *catalogue);
bool catalog_lookup(catalog *catalogue, const char *term, bool coordinates, catalog_result *result);
/* Columns: id, gaia_dr3_source_id, name, spectral_type, phot_g_mean_mag, parallax_mas,
 * teff_k, bp_rp, absolute_v_mag, phot_variable_flag (+ match_count). */
bool catalog_render_lookup(catalog *catalogue, const char *term, catalog_result *result);
bool catalog_nearest(catalog *catalogue, int64_t count, catalog_result *result);
bool catalog_recons_nearest(catalog *catalogue, int64_t count, catalog_result *result);
bool catalog_recons_lookup(catalog *catalogue, const char *term, catalog_result *result);
bool catalog_metadata(catalog *catalogue, catalog_result *result);

void print_json_string(const char *text);
void print_row(catalog_result *result, idx_t row, bool json);
void print_rows(catalog_result *result, bool json, bool array);
int print_error(bool json, int status, const char *code, const char *message);

#endif
