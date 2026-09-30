#include "catalog.h"

#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void usage(void) {
    puts("Usage: star-search [--json] info NAME_OR_ID\n"
         "       star-search [--json] star NAME_OR_ID      (alias of info)\n"
         "       star-search [--json] coords NAME_OR_ID\n"
         "       star-search [--json] nearest N\n"
         "       star-search [--json] recons-nearest [N]\n"
         "       star-search [--json] recons-info NAME_OR_ID\n"
         "       star-search [--json] render NAME_OR_ID    (not yet implemented; exit 5)\n"
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

static int report_lookup(duckdb_result *result, bool json, idx_t name_column) {
    int status = 0;
    idx_t rows = duckdb_row_count(result);
    if (!rows) {
        status = print_error(json, 3, "not_found", "No matching star in this catalog.");
    } else if (rows > 1) {
        int64_t total = duckdb_value_int64(result, duckdb_column_count(result) - 1, 0);
        if (json) {
            printf("{\"error\":\"ambiguous\",\"message\":\"Select a stable ID.\","
                   "\"match_count\":%lld,\"truncated\":%s,\"candidates\":[",
                   (long long)total, total > (int64_t)rows ? "true" : "false");
        } else {
            fprintf(stderr, "%lld matches; showing %llu. Select a stable ID.\n",
                    (long long)total, (unsigned long long)rows);
        }
        for (idx_t row = 0; row < rows; ++row) {
            char *identifier = duckdb_value_varchar(result, 0, row);
            char *name = duckdb_value_is_null(result, name_column, row) ? NULL :
                         duckdb_value_varchar(result, name_column, row);
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
        print_rows(result, json, false);
    }
    return status;
}

static int lookup(catalog *catalogue, const char *term, bool coordinates, bool json) {
    duckdb_result result = {0};
    if (!catalog_lookup(catalogue, term, coordinates, &result)) {
        duckdb_destroy_result(&result);
        return print_error(json, 1, "query_error", "Unable to query catalog.");
    }
    int status = report_lookup(&result, json, coordinates ? 1 : 2);
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
    bool recons_nearest = command && strcmp(command, "recons-nearest") == 0;
    bool recons_info = command && strcmp(command, "recons-info") == 0;
    bool coordinates = command && strcmp(command, "coords") == 0;
    /* "star" is a friendlier alias of "info"; both resolve a name or stable ID. */
    bool info = command && (strcmp(command, "info") == 0 || strcmp(command, "star") == 0);
    /* "render" is reserved for the deterministic C/GLSL renderer (assets/stars/<id>.png). */
    bool render = command && strcmp(command, "render") == 0;
    if (!invalid && argument_count == 1 && strcmp(command, "--help") == 0) {
        usage();
        return 0;
    }
    if (!invalid && argument_count == 1 && strcmp(command, "--version") == 0) {
        puts(json ? "{\"version\":\"" STAR_SEARCH_VERSION "\"}" : "star-search " STAR_SEARCH_VERSION);
        return 0;
    }
    if (invalid || (command && !metadata && !nearest && !recons_nearest && !recons_info &&
                    !coordinates && !info && !render) || (metadata && argument_count != 1) ||
        ((nearest || coordinates || info || recons_info || render) && argument_count != 2) ||
        (recons_nearest && (argument_count < 1 || argument_count > 2))) {
        return print_error(json, 2, "usage", "Invalid arguments. See star-search --help.");
    }
    if (render) {
        return print_error(json, 5, "not_implemented",
            "render is not yet implemented; the deterministic C/GLSL renderer arrives in a "
            "later phase.");
    }
    int64_t count = recons_nearest ? 100 : 0;
    if (nearest || (recons_nearest && argument_count == 2)) {
        const char *number = arguments[1];
        char *end = NULL;
        errno = 0;
        long long parsed = strtoll(number, &end, 10);
        long long maximum = recons_nearest ? 100 : 10000;
        if (!*number || strspn(number, "0123456789") != strlen(number) || errno || *end ||
            parsed < 1 || parsed > maximum) {
            return print_error(json, 2, "usage", recons_nearest ?
                "recons-nearest requires an integer from 1 through 100." :
                "nearest requires an integer from 1 through 10000.");
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
    } else if (info || coordinates || recons_info) {
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
    } else if (metadata || nearest || recons_nearest) {
        duckdb_result result = {0};
        bool success = metadata ? catalog_metadata(&catalogue, &result) :
                       nearest ? catalog_nearest(&catalogue, count, &result) :
                                 catalog_recons_nearest(&catalogue, count, &result);
        if (success) {
            print_rows(&result, json, nearest || recons_nearest);
            status = 0;
        } else {
            status = print_error(json, 1, "query_error", "Unable to query catalog.");
        }
        duckdb_destroy_result(&result);
    } else if (recons_info) {
        duckdb_result result = {0};
        if (catalog_recons_lookup(&catalogue, term, &result)) {
            status = report_lookup(&result, json, 2);
        } else {
            status = print_error(json, 1, "query_error", "Unable to query RECONS data.");
        }
        duckdb_destroy_result(&result);
    } else {
        status = lookup(&catalogue, term, coordinates, json);
    }
    catalog_close(&catalogue);
    free(input);
    return status;
}