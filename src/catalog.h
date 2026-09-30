#ifndef STAR_SEARCH_CATALOG_H
#define STAR_SEARCH_CATALOG_H

#include <duckdb.h>
#include <stdbool.h>

typedef struct {
    duckdb_database database;
    duckdb_connection connection;
    bool has_recons;
} catalog;

bool catalog_open(catalog *catalogue, const char *directory);
void catalog_close(catalog *catalogue);
bool catalog_lookup(catalog *catalogue, const char *term, bool coordinates, duckdb_result *result);
/* Columns: id, gaia_dr3_source_id, name, spectral_type, phot_g_mean_mag, parallax_mas,
 * teff_k, bp_rp, absolute_v_mag, phot_variable_flag (+ match_count). */
bool catalog_render_lookup(catalog *catalogue, const char *term, duckdb_result *result);
bool catalog_nearest(catalog *catalogue, int64_t count, duckdb_result *result);
bool catalog_recons_nearest(catalog *catalogue, int64_t count, duckdb_result *result);
bool catalog_recons_lookup(catalog *catalogue, const char *term, duckdb_result *result);
bool catalog_metadata(catalog *catalogue, duckdb_result *result);

void print_json_string(const char *text);
void print_row(duckdb_result *result, idx_t row, bool json);
void print_rows(duckdb_result *result, bool json, bool array);
int print_error(bool json, int status, const char *code, const char *message);

#endif