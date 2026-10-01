/* v1.0 catalog backend: the starsearch.online JSON API.
 *
 * The website serves one prepared dataset snapshot (built by the DuckDB/Python
 * pipeline in tools/ and web/scripts/); the CLI reads the very same snapshot
 * through these endpoints, so CLI and website always agree:
 *   info/star, coords, render -> GET /api/star/:id  (fallback /api/search?q=)
 *   nearest N                 -> GET /api/stars?sort=distance&limit=N&full=1
 *   recons-nearest, -info     -> GET /api/nearest[?q=]
 *   --catalog-info            -> GET /api/catalog
 * Rendering itself stays local (src/render.c); only the lookup is remote.
 * A future v2.0 may add an optional offline DuckDB backend behind catalog.h. */
#include "catalog.h"

#include <cjson/cJSON.h>
#include <curl/curl.h>
#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_RESPONSE_BYTES (64u * 1024u * 1024u)
#define LOOKUP_LIMIT 10

typedef struct {
    const char *column; /* CLI output column name (catalog schema 1 names) */
    const char *key;    /* field in the API's JSON record */
    result_type type;
} column_spec;

#define COLUMNS(array) (array), sizeof(array) / sizeof((array)[0])

static const column_spec star_columns[] = {
    {"id", "id", RESULT_TYPE_VARCHAR},
    {"gaia_dr3_source_id", "gaia_source_id", RESULT_TYPE_VARCHAR},
    {"name", "primary_name", RESULT_TYPE_VARCHAR},
    {"source_catalog", "source_catalogs", RESULT_TYPE_VARCHAR},
    {"ra_deg", "ra_deg", RESULT_TYPE_DOUBLE},
    {"dec_deg", "dec_deg", RESULT_TYPE_DOUBLE},
    {"ref_epoch_jyear", "ref_epoch_jyear", RESULT_TYPE_DOUBLE},
    {"parallax_mas", "parallax_mas", RESULT_TYPE_DOUBLE},
    {"parallax_error_mas", "parallax_error_mas", RESULT_TYPE_DOUBLE},
    {"distance_pc", "distance_pc", RESULT_TYPE_DOUBLE},
    {"distance_method", "distance_mode", RESULT_TYPE_VARCHAR},
    {"galactic_longitude_deg", "galactic_longitude_deg", RESULT_TYPE_DOUBLE},
    {"galactic_latitude_deg", "galactic_latitude_deg", RESULT_TYPE_DOUBLE},
    {"phot_g_mean_mag", "phot_g_mean_mag", RESULT_TYPE_DOUBLE},
    {"phot_bp_mean_mag", "phot_bp_mean_mag", RESULT_TYPE_DOUBLE},
    {"phot_rp_mean_mag", "phot_rp_mean_mag", RESULT_TYPE_DOUBLE},
    {"spectral_type", "spectral_type", RESULT_TYPE_VARCHAR},
};

static const column_spec coordinate_columns[] = {
    {"id", "id", RESULT_TYPE_VARCHAR},
    {"name", "primary_name", RESULT_TYPE_VARCHAR},
    {"ra_deg", "ra_deg", RESULT_TYPE_DOUBLE},
    {"dec_deg", "dec_deg", RESULT_TYPE_DOUBLE},
    {"ref_epoch_jyear", "ref_epoch_jyear", RESULT_TYPE_DOUBLE},
    {"galactic_longitude_deg", "galactic_longitude_deg", RESULT_TYPE_DOUBLE},
    {"galactic_latitude_deg", "galactic_latitude_deg", RESULT_TYPE_DOUBLE},
};

/* Same inputs the website's prepare_web_data.py feeds its parameter port, so
 * CLI portraits match the site's render parameters. */
static const column_spec render_columns[] = {
    {"id", "id", RESULT_TYPE_VARCHAR},
    {"gaia_dr3_source_id", "gaia_source_id", RESULT_TYPE_BIGINT},
    {"name", "primary_name", RESULT_TYPE_VARCHAR},
    {"spectral_type", "spectral_type", RESULT_TYPE_VARCHAR},
    {"phot_g_mean_mag", "phot_g_mean_mag", RESULT_TYPE_DOUBLE},
    {"parallax_mas", "parallax_mas", RESULT_TYPE_DOUBLE},
    {"teff_k", "teff_gspphot_k", RESULT_TYPE_DOUBLE},
    {"bp_rp", "bp_rp", RESULT_TYPE_DOUBLE},
    {"absolute_v_mag", "absolute_mag", RESULT_TYPE_DOUBLE},
    {"phot_variable_flag", "phot_variable_flag", RESULT_TYPE_VARCHAR},
};

#define RECONS_DETAIL_COLUMNS \
    {"ra_hms", "ra_hms", RESULT_TYPE_VARCHAR}, \
    {"dec_dms", "dec_dms", RESULT_TYPE_VARCHAR}, \
    {"ra_deg", "ra_deg", RESULT_TYPE_DOUBLE}, \
    {"dec_deg", "dec_deg", RESULT_TYPE_DOUBLE}, \
    {"ref_epoch_jyear", "ref_epoch_jyear", RESULT_TYPE_DOUBLE}, \
    {"parallax_arcsec", "parallax_arcsec", RESULT_TYPE_DOUBLE}, \
    {"parallax_error_mas", "parallax_error_mas", RESULT_TYPE_DOUBLE}, \
    {"distance_pc", "distance_pc", RESULT_TYPE_DOUBLE}, \
    {"distance_ly", "distance_ly", RESULT_TYPE_DOUBLE}, \
    {"proper_motion_arcsec_per_year", "proper_motion_arcsec_per_year", RESULT_TYPE_DOUBLE}, \
    {"proper_motion_angle_deg", "proper_motion_angle_deg", RESULT_TYPE_DOUBLE}, \
    {"proper_motion_reference", "proper_motion_reference", RESULT_TYPE_VARCHAR}, \
    {"spectral_type", "spectral_type", RESULT_TYPE_VARCHAR}, \
    {"v_mag", "v_mag", RESULT_TYPE_DOUBLE}, \
    {"v_mag_flag", "v_mag_flag", RESULT_TYPE_VARCHAR}, \
    {"v_mag_reference", "v_mag_reference", RESULT_TYPE_VARCHAR}, \
    {"absolute_mag", "absolute_mag", RESULT_TYPE_DOUBLE}, \
    {"mass_solar", "mass_solar", RESULT_TYPE_DOUBLE}, \
    {"mass_estimate_flag", "mass_estimate_flag", RESULT_TYPE_VARCHAR}, \
    {"notes", "notes", RESULT_TYPE_VARCHAR}, \
    {"x_pc", "x_pc", RESULT_TYPE_DOUBLE}, \
    {"y_pc", "y_pc", RESULT_TYPE_DOUBLE}, \
    {"z_pc", "z_pc", RESULT_TYPE_DOUBLE}, \
    {"galactic_longitude_deg", "galactic_longitude_deg", RESULT_TYPE_DOUBLE}, \
    {"galactic_latitude_deg", "galactic_latitude_deg", RESULT_TYPE_DOUBLE}, \
    {"source_catalog", "source_catalog", RESULT_TYPE_VARCHAR}

static const column_spec recons_nearest_columns[] = {
    {"id", "id", RESULT_TYPE_VARCHAR},
    {"is_recons_entry", "is_recons_entry", RESULT_TYPE_BOOLEAN},
    {"system_rank", "system_rank", RESULT_TYPE_BIGINT},
    {"cns_name", "cns_name", RESULT_TYPE_VARCHAR},
    {"component", "component", RESULT_TYPE_VARCHAR},
    {"common_name", "common_name", RESULT_TYPE_VARCHAR},
    RECONS_DETAIL_COLUMNS,
};

static const column_spec recons_lookup_columns[] = {
    {"id", "id", RESULT_TYPE_VARCHAR},
    {"cns_name", "cns_name", RESULT_TYPE_VARCHAR},
    {"common_name", "common_name", RESULT_TYPE_VARCHAR},
    {"component", "component", RESULT_TYPE_VARCHAR},
    {"system_rank", "system_rank", RESULT_TYPE_BIGINT},
    {"is_recons_entry", "is_recons_entry", RESULT_TYPE_BOOLEAN},
    RECONS_DETAIL_COLUMNS,
};

/* ---------------------------------------------------------------- HTTP --- */

typedef struct {
    char *data;
    size_t size;
    bool overflow;
} buffer;

static size_t collect(char *chunk, size_t size, size_t count, void *userdata) {
    buffer *body = userdata;
    size_t bytes = size * count;
    if (body->size + bytes > MAX_RESPONSE_BYTES) {
        body->overflow = true;
        return 0;
    }
    char *grown = realloc(body->data, body->size + bytes + 1);
    if (!grown) {
        return 0;
    }
    memcpy(grown + body->size, chunk, bytes);
    body->data = grown;
    body->size += bytes;
    body->data[body->size] = '\0';
    return bytes;
}

/* GETs base_url + path and parses the JSON body. Returns the HTTP status, or
 * -1 on a transport/parse failure (already reported on stderr, never stdout,
 * so --json output stays clean). */
static long http_get_json(catalog *catalogue, const char *path, cJSON **json) {
    *json = NULL;
    size_t length = strlen(catalogue->base_url) + strlen(path) + 1;
    char *url = malloc(length);
    if (!url) {
        return -1;
    }
    snprintf(url, length, "%s%s", catalogue->base_url, path);
    CURL *curl = catalogue->http;
    buffer body = {0};
    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, collect);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &body);
    CURLcode code = curl_easy_perform(curl);
    long status = -1;
    if (code != CURLE_OK) {
        fprintf(stderr, "star-search: cannot reach %s: %s\n", url,
                body.overflow ? "response too large" : curl_easy_strerror(code));
    } else {
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
        *json = body.data ? cJSON_Parse(body.data) : NULL;
        if (!*json) {
            fprintf(stderr, "star-search: %s returned HTTP %ld without valid JSON\n", url, status);
            status = -1;
        } else if (status != 200 && status != 404) {
            const cJSON *detail = cJSON_GetObjectItemCaseSensitive(*json, "detail");
            fprintf(stderr, "star-search: %s returned HTTP %ld%s%s\n", url, status,
                    cJSON_IsString(detail) ? ": " : "", cJSON_IsString(detail) ? detail->valuestring : "");
        }
    }
    free(body.data);
    free(url);
    return status;
}

static char *escape(catalog *catalogue, const char *text) {
    return curl_easy_escape(catalogue->http, text, 0);
}

/* ------------------------------------------------------- JSON -> table --- */

static bool init_columns(catalog_result *result, const column_spec *specs, size_t count, bool match_count) {
    if (!result_init(result, count + (match_count ? 1 : 0))) {
        return false;
    }
    for (size_t column = 0; column < count; ++column) {
        if (!result_set_column(result, column, specs[column].column, specs[column].type)) {
            return false;
        }
    }
    return !match_count || result_set_column(result, count, "match_count", RESULT_TYPE_BIGINT);
}

static bool set_cell(catalog_result *result, idx_t column, idx_t row, const cJSON *value) {
    result_cell *cell = result_cell_at(result, column, row);
    if (!cell || !value || cJSON_IsNull(value)) {
        return true;
    }
    switch (result_column_type(result, column)) {
    case RESULT_TYPE_DOUBLE:
        if (cJSON_IsNumber(value)) {
            cell->number = value->valuedouble;
        } else if (cJSON_IsString(value)) {
            cell->number = strtod(value->valuestring, NULL);
        } else {
            return true;
        }
        cell->is_null = !isfinite(cell->number);
        return true;
    case RESULT_TYPE_BIGINT:
        if (cJSON_IsNumber(value)) {
            cell->integer = (int64_t)value->valuedouble;
        } else if (cJSON_IsString(value) && *value->valuestring) {
            char *end = NULL;
            cell->integer = strtoll(value->valuestring, &end, 10);
            if (*end) {
                return true;
            }
        } else {
            return true;
        }
        cell->is_null = false;
        return true;
    case RESULT_TYPE_BOOLEAN:
        if (cJSON_IsBool(value)) {
            cell->boolean = cJSON_IsTrue(value);
            cell->is_null = false;
        }
        return true;
    default: {
        char number[64];
        const char *text = cJSON_IsString(value) ? value->valuestring : NULL;
        if (cJSON_IsNumber(value)) {
            snprintf(number, sizeof(number), "%.17g", value->valuedouble);
            text = number;
        } else if (cJSON_IsBool(value)) {
            text = cJSON_IsTrue(value) ? "true" : "false";
        }
        if (text) {
            cell->text = strdup(text);
            cell->is_null = cell->text == NULL;
            return cell->text != NULL;
        }
        return true;
    }
    }
}

static bool append_record(catalog_result *result, const column_spec *specs, size_t count,
                          const cJSON *record) {
    int64_t row = result_add_row(result);
    if (row < 0) {
        return false;
    }
    for (size_t column = 0; column < count; ++column) {
        if (!set_cell(result, column, (idx_t)row,
                      cJSON_GetObjectItemCaseSensitive(record, specs[column].key))) {
            return false;
        }
    }
    return true;
}

static void set_match_count(catalog_result *result, idx_t column, int64_t total) {
    for (idx_t row = 0; row < result_row_count(result); ++row) {
        result_cell *cell = result_cell_at(result, column, row);
        cell->integer = total;
        cell->is_null = false;
    }
}

static const char *json_text(const cJSON *object, const char *key) {
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(object, key);
    return cJSON_IsString(item) ? item->valuestring : NULL;
}

/* Case-insensitive substring test (ASCII), matching the old contains(lower()). */
static bool contains_ci(const char *haystack, const char *needle) {
    if (!haystack) {
        return false;
    }
    size_t needle_length = strlen(needle);
    for (const char *start = haystack; *start; ++start) {
        size_t index = 0;
        while (index < needle_length && start[index] &&
               tolower((unsigned char)start[index]) == tolower((unsigned char)needle[index])) {
            ++index;
        }
        if (index == needle_length) {
            return true;
        }
    }
    return needle_length == 0;
}

/* ------------------------------------------------------------ public --- */

bool catalog_open(catalog *catalogue, const char *source) {
    memset(catalogue, 0, sizeof(*catalogue));
    if (!source || (strncmp(source, "https://", 8) != 0 && strncmp(source, "http://", 7) != 0)) {
        fprintf(stderr, "star-search: STAR_SEARCH_API_URL must be an http(s):// URL\n");
        return false;
    }
    if (curl_global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK) {
        return false;
    }
    catalogue->base_url = strdup(source);
    catalogue->http = curl_easy_init();
    if (!catalogue->base_url || !catalogue->http) {
        catalog_close(catalogue);
        return false;
    }
    size_t length = strlen(catalogue->base_url);
    while (length && catalogue->base_url[length - 1] == '/') {
        catalogue->base_url[--length] = '\0';
    }
    CURL *curl = catalogue->http;
    curl_easy_setopt(curl, CURLOPT_USERAGENT, "star-search/" STAR_SEARCH_VERSION);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(curl, CURLOPT_MAXREDIRS, 5L);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 10L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 60L);
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(curl, CURLOPT_ACCEPT_ENCODING, "");
    return true;
}

void catalog_close(catalog *catalogue) {
    if (catalogue->http) {
        curl_easy_cleanup(catalogue->http);
        curl_global_cleanup();
    }
    free(catalogue->base_url);
    memset(catalogue, 0, sizeof(*catalogue));
}

/* Fetches one full star record; 1 = found, 0 = not found, -1 = error. */
static int fetch_star(catalog *catalogue, const char *term, cJSON **response, const cJSON **star) {
    char *escaped = escape(catalogue, term);
    if (!escaped) {
        return -1;
    }
    size_t length = strlen(escaped) + 16;
    char *path = malloc(length);
    long status = -1;
    if (path) {
        snprintf(path, length, "/api/star/%s", escaped);
        status = http_get_json(catalogue, path, response);
    }
    free(path);
    curl_free(escaped);
    if (status == 404) {
        return 0;
    }
    *star = status == 200 ? cJSON_GetObjectItemCaseSensitive(*response, "star") : NULL;
    return cJSON_IsObject(*star) ? 1 : -1;
}

/* Staged lookup preserving the old semantics: exact key/ID/name/alias first
 * (/api/star/:id), then a substring search (/api/search). One hit -> full
 * record; several -> up to 10 candidates (id + name) with match_count. */
static bool staged_lookup(catalog *catalogue, const char *term, const column_spec *specs,
                          size_t count, catalog_result *result) {
    cJSON *response = NULL;
    const cJSON *star = NULL;
    int found = fetch_star(catalogue, term, &response, &star);
    bool success = found >= 0 && init_columns(result, specs, count, true);
    if (success && found == 1) {
        success = append_record(result, specs, count, star);
        set_match_count(result, count, 1);
    } else if (success) {
        cJSON_Delete(response);
        response = NULL;
        char *escaped = escape(catalogue, term);
        size_t length = escaped ? strlen(escaped) + 48 : 0;
        char *path = escaped ? malloc(length) : NULL;
        long status = -1;
        if (path) {
            snprintf(path, length, "/api/search?q=%s&limit=%d", escaped, LOOKUP_LIMIT);
            status = http_get_json(catalogue, path, &response);
        }
        free(path);
        curl_free(escaped);
        const cJSON *hits = cJSON_GetObjectItemCaseSensitive(response, "results");
        const cJSON *total = cJSON_GetObjectItemCaseSensitive(response, "total");
        success = status == 200 && cJSON_IsArray(hits) && cJSON_IsNumber(total);
        int hit_count = success ? cJSON_GetArraySize(hits) : 0;
        if (success && hit_count == 1) {
            const char *identifier = json_text(cJSON_GetArrayItem(hits, 0), "id");
            cJSON *record = NULL;
            star = NULL;
            success = identifier && fetch_star(catalogue, identifier, &record, &star) == 1 &&
                      append_record(result, specs, count, star);
            set_match_count(result, count, 1);
            cJSON_Delete(record);
        } else if (success) {
            const cJSON *hit = NULL;
            cJSON_ArrayForEach(hit, hits) {
                /* Candidates carry id + name only; search hits expose the
                 * display name under "name" rather than "primary_name". */
                int64_t row = result_add_row(result);
                success = success && row >= 0 &&
                          set_cell(result, 0, (idx_t)row, cJSON_GetObjectItemCaseSensitive(hit, "id"));
                for (size_t column = 1; success && column < count; ++column) {
                    if (strcmp(specs[column].column, "name") == 0) {
                        success = set_cell(result, column, (idx_t)row,
                                           cJSON_GetObjectItemCaseSensitive(hit, "name"));
                    }
                }
            }
            set_match_count(result, count, (int64_t)total->valuedouble);
        }
    }
    cJSON_Delete(response);
    return success;
}

bool catalog_lookup(catalog *catalogue, const char *term, bool coordinates, catalog_result *result) {
    return coordinates ? staged_lookup(catalogue, term, COLUMNS(coordinate_columns), result)
                       : staged_lookup(catalogue, term, COLUMNS(star_columns), result);
}

bool catalog_render_lookup(catalog *catalogue, const char *term, catalog_result *result) {
    return staged_lookup(catalogue, term, COLUMNS(render_columns), result);
}

bool catalog_nearest(catalog *catalogue, int64_t count, catalog_result *result) {
    char path[96];
    snprintf(path, sizeof(path), "/api/stars?sort=distance&order=asc&limit=%lld&full=1", (long long)count);
    cJSON *response = NULL;
    long status = http_get_json(catalogue, path, &response);
    const cJSON *rows = cJSON_GetObjectItemCaseSensitive(response, "rows");
    bool success = status == 200 && cJSON_IsArray(rows) && init_columns(result, COLUMNS(star_columns), false);
    const cJSON *row = NULL;
    cJSON_ArrayForEach(row, rows) {
        const cJSON *distance = cJSON_GetObjectItemCaseSensitive(row, "distance_pc");
        if (!success || (int64_t)result_row_count(result) >= count) {
            break;
        }
        if (cJSON_IsNumber(distance) && isfinite(distance->valuedouble) && distance->valuedouble > 0) {
            success = append_record(result, COLUMNS(star_columns), row);
        }
    }
    cJSON_Delete(response);
    return success;
}

/* Flattens /api/nearest systems into their component rows. */
static cJSON *fetch_recons_components(catalog *catalogue, const char *query, cJSON **response) {
    char path[512] = "/api/nearest";
    if (query) {
        char *escaped = escape(catalogue, query);
        if (!escaped || strlen(escaped) > sizeof(path) - 32) {
            curl_free(escaped);
            return NULL;
        }
        snprintf(path, sizeof(path), "/api/nearest?q=%s", escaped);
        curl_free(escaped);
    }
    if (http_get_json(catalogue, path, response) != 200) {
        return NULL;
    }
    const cJSON *systems = cJSON_GetObjectItemCaseSensitive(*response, "systems");
    cJSON *components = cJSON_CreateArray();
    const cJSON *system = NULL;
    cJSON_ArrayForEach(system, systems) {
        const cJSON *component = NULL;
        cJSON_ArrayForEach(component, cJSON_GetObjectItemCaseSensitive(system, "components")) {
            cJSON_AddItemReferenceToArray(components, (cJSON *)component);
        }
    }
    return components;
}

static int compare_text(const char *left, const char *right) {
    /* NULLs sort last, as in ORDER BY ... ASC (DuckDB default). */
    return !left ? (right ? 1 : 0) : !right ? -1 : strcmp(left, right);
}

static int compare_recons(const void *left_pointer, const void *right_pointer) {
    const cJSON *left = *(const cJSON *const *)left_pointer;
    const cJSON *right = *(const cJSON *const *)right_pointer;
    const cJSON *left_rank = cJSON_GetObjectItemCaseSensitive(left, "system_rank");
    const cJSON *right_rank = cJSON_GetObjectItemCaseSensitive(right, "system_rank");
    double a = cJSON_IsNumber(left_rank) ? left_rank->valuedouble : INFINITY;
    double b = cJSON_IsNumber(right_rank) ? right_rank->valuedouble : INFINITY;
    int order = (a > b) - (a < b);
    if (!order) order = compare_text(json_text(left, "cns_name"), json_text(right, "cns_name"));
    if (!order) order = compare_text(json_text(left, "component"), json_text(right, "component"));
    if (!order) order = compare_text(json_text(left, "id"), json_text(right, "id"));
    return order;
}

/* Collects references to the components selected by `keep`, sorted by rank. */
static const cJSON **select_components(cJSON *components, bool (*keep)(const cJSON *, const void *),
                                       const void *context, size_t *selected) {
    size_t capacity = (size_t)cJSON_GetArraySize(components) + 1;
    const cJSON **rows = malloc(capacity * sizeof(*rows));
    *selected = 0;
    if (!rows) {
        return NULL;
    }
    const cJSON *component = NULL;
    cJSON_ArrayForEach(component, components) {
        /* References share the original object's children, so lookups work. */
        if (keep(component, context)) {
            rows[(*selected)++] = component;
        }
    }
    qsort(rows, *selected, sizeof(*rows), compare_recons);
    return rows;
}

static bool within_rank(const cJSON *component, const void *context) {
    const cJSON *rank = cJSON_GetObjectItemCaseSensitive(component, "system_rank");
    return cJSON_IsNumber(rank) && rank->valuedouble <= (double)*(const int64_t *)context;
}

static bool matches_term(const cJSON *component, const void *context) {
    const char *term = context;
    const char *identifier = json_text(component, "id");
    const char *cns_name = json_text(component, "cns_name");
    const char *part = json_text(component, "component");
    char combined[512];
    snprintf(combined, sizeof(combined), "%s %s", cns_name ? cns_name : "", part ? part : "");
    return (identifier && strcmp(identifier, term) == 0) || contains_ci(cns_name, term) ||
           (cns_name && contains_ci(combined, term)) ||
           contains_ci(json_text(component, "common_name"), term);
}

bool catalog_recons_nearest(catalog *catalogue, int64_t count, catalog_result *result) {
    cJSON *response = NULL;
    cJSON *components = fetch_recons_components(catalogue, NULL, &response);
    size_t selected = 0;
    const cJSON **rows = components ? select_components(components, within_rank, &count, &selected) : NULL;
    bool success = rows && init_columns(result, COLUMNS(recons_nearest_columns), false);
    for (size_t index = 0; success && index < selected; ++index) {
        success = append_record(result, COLUMNS(recons_nearest_columns), rows[index]);
    }
    free(rows);
    cJSON_Delete(components);
    cJSON_Delete(response);
    return success;
}

bool catalog_recons_lookup(catalog *catalogue, const char *term, catalog_result *result) {
    /* The server-side ?q= filter narrows to matching systems by name; exact
     * component IDs (recons:...) are not indexed there, so fall back to the
     * full list when the filtered request yields no match. */
    bool success = false;
    for (int attempt = 0; attempt < 2 && !success; ++attempt) {
        cJSON *response = NULL;
        cJSON *components = fetch_recons_components(catalogue, attempt == 0 ? term : NULL, &response);
        size_t selected = 0;
        const cJSON **rows = components ? select_components(components, matches_term, term, &selected) : NULL;
        bool fetched = rows != NULL;
        if (rows && (selected || attempt == 1)) {
            success = init_columns(result, COLUMNS(recons_lookup_columns), true);
            size_t columns = sizeof(recons_lookup_columns) / sizeof(recons_lookup_columns[0]);
            for (size_t index = 0; success && index < selected && index < LOOKUP_LIMIT; ++index) {
                success = append_record(result, COLUMNS(recons_lookup_columns), rows[index]);
            }
            set_match_count(result, columns, (int64_t)selected);
        }
        free(rows);
        cJSON_Delete(components);
        cJSON_Delete(response);
        if (!fetched) {
            break;
        }
    }
    return success;
}

/* --catalog-info: the dataset manifest flattened into one row; nested object
 * keys are joined with '_' (e.g. counts_stars). Arrays are omitted. */
static size_t flatten(const cJSON *object, const char *prefix, catalog_result *result, size_t column) {
    const cJSON *item = NULL;
    cJSON_ArrayForEach(item, object) {
        char name[256];
        snprintf(name, sizeof(name), "%s%s%s", prefix, *prefix ? "_" : "", item->string);
        if (cJSON_IsObject(item)) {
            column = flatten(item, name, result, column);
        } else if (cJSON_IsString(item) || cJSON_IsNumber(item) || cJSON_IsBool(item)) {
            if (result) {
                result_type type = cJSON_IsString(item) ? RESULT_TYPE_VARCHAR :
                                   cJSON_IsBool(item) ? RESULT_TYPE_BOOLEAN :
                                   (item->valuedouble == floor(item->valuedouble) &&
                                    fabs(item->valuedouble) < 9007199254740992.0) ?
                                   RESULT_TYPE_BIGINT : RESULT_TYPE_DOUBLE;
                result_set_column(result, column, name, type);
                set_cell(result, column, 0, item);
            }
            ++column;
        }
    }
    return column;
}

bool catalog_metadata(catalog *catalogue, catalog_result *result) {
    cJSON *manifest = NULL;
    bool success = http_get_json(catalogue, "/api/catalog", &manifest) == 200 && cJSON_IsObject(manifest);
    if (success) {
        size_t columns = flatten(manifest, "", NULL, 0) + 1;
        success = result_init(result, columns) && result_add_row(result) == 0 &&
                  result_set_column(result, 0, "api_url", RESULT_TYPE_VARCHAR);
        if (success) {
            result_cell *cell = result_cell_at(result, 0, 0);
            cell->text = strdup(catalogue->base_url);
            cell->is_null = cell->text == NULL;
            flatten(manifest, "", result, 1);
        }
    }
    cJSON_Delete(manifest);
    return success;
}
