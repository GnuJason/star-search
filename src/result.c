#include "result.h"

#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

bool result_init(catalog_result *result, idx_t columns) {
    memset(result, 0, sizeof(*result));
    result->names = calloc(columns ? columns : 1, sizeof(*result->names));
    result->types = calloc(columns ? columns : 1, sizeof(*result->types));
    if (!result->names || !result->types) {
        result_destroy(result);
        return false;
    }
    result->column_count = columns;
    return true;
}

bool result_set_column(catalog_result *result, idx_t column, const char *name, result_type type) {
    if (column >= result->column_count) {
        return false;
    }
    free(result->names[column]);
    result->names[column] = strdup(name);
    result->types[column] = type;
    return result->names[column] != NULL;
}

int64_t result_add_row(catalog_result *result) {
    if (result->row_count == result->row_capacity) {
        idx_t capacity = result->row_capacity ? result->row_capacity * 2 : 16;
        result_cell *cells = realloc(result->cells, capacity * result->column_count * sizeof(*cells));
        if (!cells) {
            return -1;
        }
        result->cells = cells;
        result->row_capacity = capacity;
    }
    idx_t row = result->row_count++;
    for (idx_t column = 0; column < result->column_count; ++column) {
        result_cell *cell = &result->cells[row * result->column_count + column];
        memset(cell, 0, sizeof(*cell));
        cell->is_null = true;
    }
    return (int64_t)row;
}

result_cell *result_cell_at(catalog_result *result, idx_t column, idx_t row) {
    if (!result->cells || column >= result->column_count || row >= result->row_count) {
        return NULL;
    }
    return &result->cells[row * result->column_count + column];
}

void result_destroy(catalog_result *result) {
    for (idx_t index = 0; result->cells && index < result->row_count * result->column_count; ++index) {
        free(result->cells[index].text);
    }
    for (idx_t column = 0; result->names && column < result->column_count; ++column) {
        free(result->names[column]);
    }
    free(result->cells);
    free(result->names);
    free(result->types);
    memset(result, 0, sizeof(*result));
}

idx_t result_row_count(catalog_result *result) {
    return result->row_count;
}

idx_t result_column_count(catalog_result *result) {
    return result->column_count;
}

const char *result_column_name(catalog_result *result, idx_t column) {
    return column < result->column_count && result->names[column] ? result->names[column] : "";
}

result_type result_column_type(catalog_result *result, idx_t column) {
    return column < result->column_count ? result->types[column] : RESULT_TYPE_VARCHAR;
}

bool result_value_is_null(catalog_result *result, idx_t column, idx_t row) {
    result_cell *cell = result_cell_at(result, column, row);
    return !cell || cell->is_null;
}

double result_value_double(catalog_result *result, idx_t column, idx_t row) {
    result_cell *cell = result_cell_at(result, column, row);
    if (!cell || cell->is_null) {
        return NAN;
    }
    switch (result->types[column]) {
    case RESULT_TYPE_DOUBLE: return cell->number;
    case RESULT_TYPE_BIGINT: return (double)cell->integer;
    case RESULT_TYPE_BOOLEAN: return cell->boolean ? 1.0 : 0.0;
    default: return cell->text ? strtod(cell->text, NULL) : NAN;
    }
}

int64_t result_value_int64(catalog_result *result, idx_t column, idx_t row) {
    result_cell *cell = result_cell_at(result, column, row);
    if (!cell || cell->is_null) {
        return 0;
    }
    switch (result->types[column]) {
    case RESULT_TYPE_BIGINT: return cell->integer;
    case RESULT_TYPE_DOUBLE: return isfinite(cell->number) ? (int64_t)cell->number : 0;
    case RESULT_TYPE_BOOLEAN: return cell->boolean;
    default: {
        if (!cell->text) {
            return 0;
        }
        errno = 0;
        char *end = NULL;
        long long value = strtoll(cell->text, &end, 10);
        return errno || end == cell->text || *end ? 0 : (int64_t)value;
    }
    }
}

bool result_value_boolean(catalog_result *result, idx_t column, idx_t row) {
    result_cell *cell = result_cell_at(result, column, row);
    if (!cell || cell->is_null) {
        return false;
    }
    switch (result->types[column]) {
    case RESULT_TYPE_BOOLEAN: return cell->boolean;
    case RESULT_TYPE_BIGINT: return cell->integer != 0;
    case RESULT_TYPE_DOUBLE: return cell->number != 0.0;
    default: return cell->text && strcmp(cell->text, "true") == 0;
    }
}

char *result_value_varchar(catalog_result *result, idx_t column, idx_t row) {
    result_cell *cell = result_cell_at(result, column, row);
    if (!cell || cell->is_null) {
        return NULL;
    }
    char buffer[64];
    switch (result->types[column]) {
    case RESULT_TYPE_DOUBLE: snprintf(buffer, sizeof(buffer), "%.17g", cell->number); break;
    case RESULT_TYPE_BIGINT: snprintf(buffer, sizeof(buffer), "%lld", (long long)cell->integer); break;
    case RESULT_TYPE_BOOLEAN: snprintf(buffer, sizeof(buffer), "%s", cell->boolean ? "true" : "false"); break;
    default: return cell->text ? strdup(cell->text) : NULL;
    }
    return strdup(buffer);
}

void result_free(void *pointer) {
    free(pointer);
}
