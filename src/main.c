#include "catalog.h"
#include "render.h"
#include "star_params.h"

#include <ctype.h>
#include <errno.h>
#include <math.h>
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
         "       star-search [--json] render NAME_OR_ID [--size PX] [-o FILE.png] [--phase P]\n"
         "       star-search [--json] --catalog-info\n"
         "       star-search [--json] --version\n"
         "       star-search [--json]\n\n"
         "Catalog directory: STAR_SEARCH_DATA_DIR (default: " STAR_SEARCH_DATA_DIR ")\n"
         "render writes $STAR_SEARCH_ASSETS_DIR/<source_id>.png (default assets/stars/);\n"
         "  --size 16..4096 (default 512), --phase 0..1 for Gaia-flagged variables.\n"
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

typedef struct {
    int size;
    const char *output;
    double phase;
} render_options;

static double column_double(duckdb_result *result, idx_t column) {
    return duckdb_value_is_null(result, column, 0) ? NAN : duckdb_value_double(result, column, 0);
}

static char *column_text(duckdb_result *result, idx_t column) {
    return duckdb_value_is_null(result, column, 0) ? NULL : duckdb_value_varchar(result, column, 0);
}

/* Default portrait path: <assets>/<gaia source_id>.png, or the catalog id with
 * every character outside [A-Za-z0-9._-] replaced by '-' for non-Gaia stars
 * (e.g. recons:gj-559:a -> recons-gj-559-a.png). */
static char *default_output_path(const star_inputs *inputs) {
    const char *directory = getenv("STAR_SEARCH_ASSETS_DIR");
    if (!directory || !*directory) {
        directory = "assets/stars";
    }
    char stem[256];
    if (inputs->has_source_id) {
        snprintf(stem, sizeof(stem), "%lld", (long long)inputs->source_id);
    } else {
        snprintf(stem, sizeof(stem), "%s", inputs->id);
        for (char *cursor = stem; *cursor; ++cursor) {
            if (!isalnum((unsigned char)*cursor) && !strchr("._-", *cursor)) {
                *cursor = '-';
            }
        }
    }
    size_t length = strlen(directory) + strlen(stem) + 6;
    char *path = malloc(length);
    if (path) {
        snprintf(path, length, "%s/%s.png", directory, stem);
    }
    return path;
}

static void print_json_number(double value) {
    if (isfinite(value)) {
        printf("%.10g", value);
    } else {
        fputs("null", stdout);
    }
}

static void print_json_text(const char *text) {
    if (text) {
        print_json_string(text);
    } else {
        fputs("null", stdout);
    }
}

static int render_command(catalog *catalogue, const char *term, const render_options *options,
                          bool json) {
    duckdb_result result = {0};
    if (!catalog_render_lookup(catalogue, term, &result)) {
        duckdb_destroy_result(&result);
        return print_error(json, 1, "query_error", "Unable to query catalog.");
    }
    if (duckdb_row_count(&result) != 1) {
        int status = report_lookup(&result, json, 2);
        duckdb_destroy_result(&result);
        return status;
    }
    char *identifier = column_text(&result, 0);
    char *name = column_text(&result, 2);
    char *spectral_type = column_text(&result, 3);
    char *variable_flag = column_text(&result, 9);
    star_inputs inputs = {
        .id = identifier,
        .has_source_id = !duckdb_value_is_null(&result, 1, 0),
        .source_id = duckdb_value_int64(&result, 1, 0),
        .spectral_type = spectral_type,
        .variable_flag = variable_flag,
        .phot_g_mean_mag = column_double(&result, 4),
        .parallax_mas = column_double(&result, 5),
        .teff_k = column_double(&result, 6),
        .bp_rp = column_double(&result, 7),
        .absolute_v_mag = column_double(&result, 8),
    };
    star_render_params params;
    star_derive_params(&inputs, options->phase, &params);

    int status = 0;
    char *path = options->output ? strdup(options->output) : default_output_path(&inputs);
    size_t pixels = (size_t)options->size * (size_t)options->size;
    uint8_t *rgb = malloc(pixels * 3);
    if (!path || !rgb) {
        status = print_error(json, 1, "memory_error", "Unable to allocate the image.");
    } else {
        render_star(&params, options->size, options->size, rgb);
        if (!write_png(path, options->size, options->size, rgb)) {
            status = print_error(json, 1, "write_error", "Unable to write the PNG output file.");
        }
    }
    if (!status && json) {
        fputs("{\"id\":", stdout);
        print_json_text(identifier);
        fputs(",\"name\":", stdout);
        print_json_text(name);
        fputs(",\"gaia_dr3_source_id\":", stdout);
        if (inputs.has_source_id) {
            printf("%lld", (long long)inputs.source_id);
        } else {
            fputs("null", stdout);
        }
        fputs(",\"output\":", stdout);
        print_json_string(path);
        printf(",\"width\":%d,\"height\":%d,\"format\":\"png\",\"parameters\":{\"teff_k\":",
               options->size, options->size);
        print_json_number(params.teff_k);
        fputs(",\"teff_source\":", stdout);
        print_json_text(params.teff_source);
        fputs(",\"spectral_type\":", stdout);
        print_json_text(spectral_type);
        fputs(",\"absolute_mag\":", stdout);
        print_json_number(params.absolute_mag);
        fputs(",\"absolute_mag_band\":", stdout);
        print_json_text(params.absolute_mag_band);
        fputs(",\"bolometric_correction\":", stdout);
        print_json_number(params.bolometric_correction);
        fputs(",\"luminosity_solar\":", stdout);
        print_json_number(params.luminosity_solar);
        fputs(",\"radius_solar\":", stdout);
        print_json_number(params.radius_solar);
        fputs(",\"radius_source\":", stdout);
        print_json_text(params.radius_source);
        fputs(",\"disk_radius_fraction\":", stdout);
        print_json_number(params.disk_radius);
        fputs(",\"limb_darkening_u1\":", stdout);
        print_json_number(params.limb_u1);
        fputs(",\"limb_darkening_u2\":", stdout);
        print_json_number(params.limb_u2);
        fputs(",\"granulation_amplitude\":", stdout);
        print_json_number(params.granulation_amplitude);
        fputs(",\"granulation_frequency\":", stdout);
        print_json_number(params.granulation_frequency);
        printf(",\"variable\":%s,\"variability_amplitude\":", params.variable ? "true" : "false");
        print_json_number(params.variability_amplitude);
        fputs(",\"phase\":", stdout);
        print_json_number(params.phase);
        printf(",\"seed\":%lu}}\n", (unsigned long)params.seed);
    } else if (!status) {
        printf("%-24s  %s\n%-24s  %s\n%-24s  %s\n%-24s  %dx%d\n%-24s  %.0f K (%s)\n",
               "id", identifier, "name", name ? name : "unknown", "output", path,
               "size", options->size, options->size, "teff", params.teff_k, params.teff_source);
        if (isfinite(params.luminosity_solar)) {
            printf("%-24s  %.4g Lsun (M_%s %.3f, BC %.3f)\n", "luminosity",
                   params.luminosity_solar, params.absolute_mag_band, params.absolute_mag,
                   params.bolometric_correction);
        }
        printf("%-24s  %.4g Rsun (%s)\n%-24s  %.3f of half-frame\n%-24s  u1=%.3f u2=%.3f\n"
               "%-24s  %s (amplitude %.2f, phase %.3f)\n%-24s  %lu\n",
               "radius", params.radius_solar, params.radius_source, "disk_radius",
               params.disk_radius, "limb_darkening", params.limb_u1, params.limb_u2,
               "variable", params.variable ? "yes" : "no", params.variability_amplitude,
               params.phase, "seed", (unsigned long)params.seed);
    }
    free(rgb);
    free(path);
    duckdb_free(identifier);
    duckdb_free(name);
    duckdb_free(spectral_type);
    duckdb_free(variable_flag);
    duckdb_destroy_result(&result);
    return status;
}

static bool parse_integer(const char *text, long minimum, long maximum, int *out) {
    char *end = NULL;
    errno = 0;
    long value = strtol(text, &end, 10);
    if (!*text || *end || errno || value < minimum || value > maximum) {
        return false;
    }
    *out = (int)value;
    return true;
}

static bool parse_phase(const char *text, double *out) {
    char *end = NULL;
    errno = 0;
    double value = strtod(text, &end);
    if (!*text || *end || errno || !isfinite(value) || value < 0.0 || value > 1.0) {
        return false;
    }
    *out = value;
    return true;
}

int main(int argc, char **argv) {
    bool json = false;
    const char *arguments[2] = {0};
    int argument_count = 0;
    bool invalid = false;
    bool positional = false;
    render_options options = {RENDER_DEFAULT_SIZE, NULL, 0.0};
    bool render_flags = false;
    for (int index = 1; index < argc; ++index) {
        if (!positional && strcmp(argv[index], "--json") == 0) {
            json = true;
        } else if (!positional && (strcmp(argv[index], "--size") == 0 ||
                                   strcmp(argv[index], "-o") == 0 ||
                                   strcmp(argv[index], "--output") == 0 ||
                                   strcmp(argv[index], "--phase") == 0)) {
            const char *flag = argv[index];
            const char *value = index + 1 < argc ? argv[++index] : NULL;
            render_flags = true;
            if (!value || (strcmp(flag, "--size") == 0 &&
                           !parse_integer(value, RENDER_MIN_SIZE, RENDER_MAX_SIZE, &options.size)) ||
                (strcmp(flag, "--phase") == 0 && !parse_phase(value, &options.phase)) ||
                ((strcmp(flag, "-o") == 0 || strcmp(flag, "--output") == 0) && !*value)) {
                invalid = true;
            } else if (strcmp(flag, "-o") == 0 || strcmp(flag, "--output") == 0) {
                options.output = value;
            }
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
    /* "render" evaluates src/shaders/star.frag on the CPU and writes a PNG portrait. */
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
        (recons_nearest && (argument_count < 1 || argument_count > 2)) ||
        (render_flags && !render)) {
        return print_error(json, 2, "usage", "Invalid arguments. See star-search --help.");
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
    } else if (info || coordinates || recons_info || render) {
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
    } else if (render) {
        status = render_command(&catalogue, term, &options, json);
    } else {
        status = lookup(&catalogue, term, coordinates, json);
    }
    /* Point users at the companion website for interactive exploration. Shown
     * only for the info/star lookup, the render command, and the interactive
     * prompt, and only in human-readable mode: --json output (which the website
     * itself consumes) stays machine-clean. */
    if (status == 0 && !json && (info || render || (!command && term != NULL))) {
        puts("\nExplore the interactive catalog, star portraits, and 3D map at "
             "https://starsearch.online");
    }
    catalog_close(&catalogue);
    free(input);
    return status;
}