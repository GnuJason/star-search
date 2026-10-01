#ifndef STAR_SEARCH_RESULT_H
#define STAR_SEARCH_RESULT_H

/* A small in-memory, column-typed result table. It decouples the CLI's
 * formatting/dispatch code (main.c, format.c) from the data backend: the v1.0
 * HTTP backend fills it from the starsearch.online JSON API, and a future
 * optional local backend (v2.0, e.g. DuckDB for offline use) can fill the same
 * table without touching the callers. */

#include <stdbool.h>
#include <stdint.h>

typedef uint64_t idx_t;

typedef enum {
    RESULT_TYPE_VARCHAR,
    RESULT_TYPE_DOUBLE,
    RESULT_TYPE_BIGINT,
    RESULT_TYPE_BOOLEAN,
} result_type;

typedef struct {
    bool is_null;
    double number;
    int64_t integer;
    bool boolean;
    char *text;
} result_cell;

typedef struct {
    idx_t column_count;
    idx_t row_count;
    idx_t row_capacity;
    char **names;
    result_type *types;
    result_cell *cells; /* row-major: cells[row * column_count + column] */
} catalog_result;

bool result_init(catalog_result *result, idx_t columns);
bool result_set_column(catalog_result *result, idx_t column, const char *name, result_type type);
/* Appends a row of NULL cells and returns its index, or -1 on allocation failure. */
int64_t result_add_row(catalog_result *result);
result_cell *result_cell_at(catalog_result *result, idx_t column, idx_t row);
void result_destroy(catalog_result *result);

idx_t result_row_count(catalog_result *result);
idx_t result_column_count(catalog_result *result);
const char *result_column_name(catalog_result *result, idx_t column);
result_type result_column_type(catalog_result *result, idx_t column);
bool result_value_is_null(catalog_result *result, idx_t column, idx_t row);
double result_value_double(catalog_result *result, idx_t column, idx_t row);
int64_t result_value_int64(catalog_result *result, idx_t column, idx_t row);
bool result_value_boolean(catalog_result *result, idx_t column, idx_t row);
/* Returns a malloc'd string (release with result_free) or NULL for NULL cells. */
char *result_value_varchar(catalog_result *result, idx_t column, idx_t row);
void result_free(void *pointer);

#endif
