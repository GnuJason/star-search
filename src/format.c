#include "catalog.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

void print_json_string(const char *text) {
    putchar('"');
    for (const unsigned char *cursor = (const unsigned char *)text; *cursor; ++cursor) {
        if (*cursor == '"' || *cursor == '\\') {
            putchar('\\');
            putchar(*cursor);
        } else if (*cursor < 0x20) {
            printf("\\u%04x", *cursor);
        } else {
            putchar(*cursor);
        }
    }
    putchar('"');
}

static void print_text(const char *text) {
    for (const unsigned char *cursor = (const unsigned char *)text; *cursor; ++cursor) {
        if (*cursor < 0x20 || *cursor == 0x7f) {
            printf("\\x%02x", *cursor);
        } else {
            putchar(*cursor);
        }
    }
}

static void print_value(duckdb_result *result, idx_t column, idx_t row, bool json) {
    if (duckdb_value_is_null(result, column, row)) {
        fputs(json ? "null" : "unknown", stdout);
        return;
    }
    duckdb_type type = duckdb_column_type(result, column);
    if (type == DUCKDB_TYPE_DOUBLE || type == DUCKDB_TYPE_FLOAT) {
        double value = duckdb_value_double(result, column, row);
        if (!isfinite(value)) {
            fputs(json ? "null" : "unknown", stdout);
        } else {
            printf(json ? "%.17g" : "%.8g", value);
        }
    } else if (type == DUCKDB_TYPE_BOOLEAN) {
        fputs(duckdb_value_boolean(result, column, row) ? "true" : "false", stdout);
    } else if (type == DUCKDB_TYPE_INTEGER || type == DUCKDB_TYPE_BIGINT) {
        printf("%lld", (long long)duckdb_value_int64(result, column, row));
    } else {
        char *value = duckdb_value_varchar(result, column, row);
        if (!value) {
            fputs(json ? "null" : "unknown", stdout);
        } else if (json) {
            print_json_string(value);
        } else {
            print_text(value);
        }
        duckdb_free(value);
    }
}

void print_row(duckdb_result *result, idx_t row, bool json) {
    bool has_distance_ly = false;
    for (idx_t column = 0; column < duckdb_column_count(result); ++column) {
        if (strcmp(duckdb_column_name(result, column), "distance_ly") == 0) {
            has_distance_ly = true;
            break;
        }
    }
    if (json) {
        putchar('{');
    }
    bool first = true;
    for (idx_t column = 0; column < duckdb_column_count(result); ++column) {
        const char *name = duckdb_column_name(result, column);
        if (strcmp(name, "match_count") == 0) {
            continue;
        }
        if (json) {
            if (!first) {
                putchar(',');
            }
            print_json_string(name);
            putchar(':');
        } else {
            printf("%-24s  ", name);
        }
        print_value(result, column, row, json);
        if (!json) {
            putchar('\n');
            if (strcmp(name, "distance_pc") == 0 && !has_distance_ly) {
                if (duckdb_value_is_null(result, column, row)) {
                    printf("%-24s  unknown\n%-24s  unknown\n", "distance_ly", "distance_ld");
                } else {
                    double light_years = duckdb_value_double(result, column, row) * 3.2615637771674336;
                    printf("%-24s  %.8g\n%-24s  %.8g\n", "distance_ly", light_years,
                           "distance_ld", light_years * 365.25);
                }
            }
        }
        first = false;
    }
    if (json) {
        putchar('}');
    }
}

void print_rows(duckdb_result *result, bool json, bool array) {
    if (json && array) {
        putchar('[');
    }
    for (idx_t row = 0; row < duckdb_row_count(result); ++row) {
        if (row) {
            fputs(json ? "," : "\n", stdout);
        }
        print_row(result, row, json);
    }
    if (json && array) {
        putchar(']');
    }
    if (json) {
        putchar('\n');
    }
}

int print_error(bool json, int status, const char *code, const char *message) {
    if (json) {
        fputs("{\"error\":", stdout);
        print_json_string(code);
        fputs(",\"message\":", stdout);
        print_json_string(message);
        puts("}");
    } else {
        fprintf(stderr, "star-search: %s\n", message);
    }
    return status;
}