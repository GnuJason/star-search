#include "catalog.h"

#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void usage(void) {
    puts("Usage: star-search [--json] info NAME_OR_ID\n"
         "       star-search [--json] coords NAME_OR_ID\n"
         "       star-search [--json] nearest N\n"
         "       star-search [--json] --catalog-info\n"
         "       star-search [--json] --version\n"
         "       star-search [--json]\n\n"
         "Catalog directory: STAR_SEARCH_DATA_DIR (default: " STAR_SEARCH_DATA_DIR ")\n"
         "Quote names containing spaces. Missing measurements are unknown/null.");
}

static char *trim(char *text) {
    while (*text && isspace((unsigned char)*text)) {
        ++text;
    }
    size_t length = strlen(text);
    while (length && isspace((unsigned char)text[length - 1])) {
        text[--length] = '\0';
    }
    return text;
}

static int lookup(catalog *catalogue, const char *term, bool coordinates, bool json) {
    duckdb_result result = {0};
    if (!catalog_lookup(catalogue, term, coordinates, &result)) {
        duckdb_destroy_result(&result);
        return print_error(json, 1, "query_error", "Unable to query catalog.");
    }
    int status = 0;
    idx_t rows = duckdb_row_count(&result);
    if (!rows) {
        status = print_error(json, 3, "not_found", "No matching star in this catalog.");
    } else if (rows > 1) {
        int64_t total = duckdb_value_int64(&result, duckdb_column_count(&result) - 1, 0);
        if (json) {
            printf("{\"error\":\"ambiguous\",\"message\":\"Select a stable ID.\","
                   "\"match_count\":%lld,\"truncated\":%s,\"candidates\":[",
                   (long long)total, total > (int64_t)rows ? "true" : "false");
        } else {
            fprintf(stderr, "%lld matches; showing %llu. Select a stable ID.\n",
                    (long long)total, (unsigned long long)rows);
        }
        idx_t name_column = coordinates ? 1 : 2;
        for (idx_t row = 0; row < rows; ++row) {
            char *identifier = duckdb_value_varchar(&result, 0, row);
            char *name = duckdb_value_is_null(&result, name_column, row) ? NULL :
                         duckdb_value_varchar(&result, name_column, row);
            if (json) {
                if (row) {
                    putchar(',');
                }
                fputs("{\"id\":", stdout);
                print_json_string(identifier ? identifier : "");
                fputs(",\"name\":", stdout);
                if (name) {
                    print_json_string(name);
                } else {
                    fputs("null", stdout);
                }
                putchar('}');
            } else {
                print_json_string(identifier ? identifier : "");
                fputs("  ", stdout);
                print_json_string(name ? name : "unknown");
                putchar('\n');
            }
            duckdb_free(identifier);
            duckdb_free(name);
        }
        if (json) {
            puts("]}");
        }
        status = 4;
    } else {
        print_rows(&result, json, false);
    }
    duckdb_destroy_result(&result);
    return status;
}

int main(int argc, char **argv) {
    bool json = false;
    const char *arguments[2] = {0};
    int argument_count = 0;
    bool invalid = false;
    bool positional = false;
    for (int index = 1; index < argc; ++index) {
        if (!positional && strcmp(argv[index], "--json") == 0) {
            json = true;
        } else if (!positional && strcmp(argv[index], "--") == 0) {
            positional = true;
        } else if (argument_count < 2) {
            arguments[argument_count++] = argv[index];
        } else {
            invalid = true;
        }
    }
    const char *command = argument_count ? arguments[0] : NULL;
    bool metadata = command && strcmp(command, "--catalog-info") == 0;
    bool nearest = command && strcmp(command, "nearest") == 0;
    bool coordinates = command && strcmp(command, "coords") == 0;
    bool info = command && strcmp(command, "info") == 0;
    if (!invalid && argument_count == 1 && strcmp(command, "--help") == 0) {
        usage();
        return 0;
    }
    if (!invalid && argument_count == 1 && strcmp(command, "--version") == 0) {
        puts(json ? "{\"version\":\"" STAR_SEARCH_VERSION "\"}" : "star-search " STAR_SEARCH_VERSION);
        return 0;
    }
    if (invalid || (command && !metadata && !nearest && !coordinates && !info) ||
        (metadata && argument_count != 1) || ((nearest || coordinates || info) && argument_count != 2)) {
        return print_error(json, 2, "usage", "Invalid arguments. See star-search --help.");
    }
    int64_t count = 0;
    if (nearest) {
        const char *number = arguments[1];
        char *end = NULL;
        errno = 0;
        long long parsed = strtoll(number, &end, 10);
        if (!*number || strspn(number, "0123456789") != strlen(number) || errno || *end || parsed < 1 || parsed > 10000) {
            return print_error(json, 2, "usage", "nearest requires an integer from 1 through 10000.");
        }
        count = parsed;
    }
    char *input = NULL;
    char *term = NULL;
    if (!command) {
        size_t capacity = 0;
        fputs("Which star would you like to find? ", stderr);
        if (getline(&input, &capacity, stdin) < 0) {
            free(input);
            return print_error(json, 2, "usage", "No star name or ID supplied.");
        }
        term = trim(input);
    } else if (info || coordinates) {
        input = strdup(arguments[1]);
        if (!input) {
            return print_error(json, 1, "memory_error", "Unable to allocate input.");
        }
        term = trim(input);
    }
    if (term && !*term) {
        free(input);
        return print_error(json, 2, "usage", "Star name or ID must not be empty.");
    }
    const char *directory = getenv("STAR_SEARCH_DATA_DIR");
    if (!directory || !*directory) {
        directory = STAR_SEARCH_DATA_DIR;
    }
    catalog catalogue = {0};
    int status;
    if (!catalog_open(&catalogue, directory)) {
        status = print_error(json, 1, "catalog_error",
            "Cannot open catalog. Install star-search-data or set STAR_SEARCH_DATA_DIR; "
            "DuckDB must include built-in Parquet and JSON support.");
    } else if (metadata || nearest) {
        duckdb_result result = {0};
        bool success = metadata ? catalog_metadata(&catalogue, &result) :
                                  catalog_nearest(&catalogue, count, &result);
        if (success) {
            print_rows(&result, json, nearest);
            status = 0;
        } else {
            status = print_error(json, 1, "query_error", "Unable to query catalog.");
        }
        duckdb_destroy_result(&result);
    } else {
        status = lookup(&catalogue, term, coordinates, json);
    }
    catalog_close(&catalogue);
    free(input);
    return status;
}