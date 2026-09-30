#include "catalog.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static const char *star_columns =
    "id, CAST(gaia_dr3_source_id AS VARCHAR) AS gaia_dr3_source_id, name, source_catalog, "
    "ra_deg, dec_deg, ref_epoch_jyear, parallax_mas, parallax_error_mas, distance_pc, "
    "distance_method, galactic_longitude_deg, galactic_latitude_deg, "
    "phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, spectral_type";
static const char *coordinate_columns =
    "id, name, ra_deg, dec_deg, ref_epoch_jyear, galactic_longitude_deg, galactic_latitude_deg";

static bool execute(catalog *catalogue, const char *sql) {
    duckdb_result result;
    bool success = duckdb_query(catalogue->connection, sql, &result) == DuckDBSuccess;
    if (!success) {
        fprintf(stderr, "star-search: %s\n", duckdb_result_error(&result));
    }
    duckdb_destroy_result(&result);
    return success;
}

static char *local_file_literal(const char *path) {
    char *resolved = realpath(path, NULL);
    struct stat attributes;
    if (!resolved || stat(resolved, &attributes) != 0 || !S_ISREG(attributes.st_mode) ||
        strpbrk(resolved, "*?[]")) {
        fprintf(stderr, "star-search: %s must be a local regular file without glob characters\n", path);
        free(resolved);
        return NULL;
    }
    size_t length = strlen(resolved);
    char *literal = malloc(length * 2 + 3);
    if (!literal) {
        free(resolved);
        return NULL;
    }
    char *output = literal;
    *output++ = '\'';
    for (const char *cursor = resolved; *cursor; ++cursor) {
        if (*cursor == '\'') {
            *output++ = '\'';
        }
        *output++ = *cursor;
    }
    *output++ = '\'';
    *output = '\0';
    free(resolved);
    return literal;
}

static char *local_path_literal(const char *directory, const char *filename) {
    size_t length = strlen(directory) + strlen(filename) + 2;
    char *path = malloc(length);
    if (!path) {
        return NULL;
    }
    snprintf(path, length, "%s/%s", directory, filename);
    char *literal = local_file_literal(path);
    free(path);
    return literal;
}

static bool create_view(catalog *catalogue, const char *directory, const char *filename,
                        const char *prefix, const char *suffix) {
    char *literal = local_path_literal(directory, filename);
    if (!literal) {
        return false;
    }
    size_t length = strlen(prefix) + strlen(literal) + strlen(suffix) + 1;
    char *sql = malloc(length);
    bool success = false;
    if (sql) {
        snprintf(sql, length, "%s%s%s", prefix, literal, suffix);
        success = execute(catalogue, sql);
    }
    free(sql);
    free(literal);
    return success;
}

static bool create_recons_view(catalog *catalogue, const char *directory) {
    const char *configured_path = getenv("STAR_SEARCH_RECONS_DATA");
    bool explicitly_configured = configured_path && *configured_path;
    size_t length = explicitly_configured ? strlen(configured_path) + 1 :
                    strlen(directory) + strlen("/recons_nearest.parquet") + 1;
    char *path = malloc(length);
    if (!path) {
        return false;
    }
    snprintf(path, length, "%s", explicitly_configured ? configured_path :
             "");
    if (!explicitly_configured) {
        snprintf(path, length, "%s/recons_nearest.parquet", directory);
    }
    if (!explicitly_configured && access(path, F_OK) != 0) {
        free(path);
        return true;
    }

    char *literal = local_file_literal(path);
    free(path);
    if (!literal) {
        return !explicitly_configured;
    }
    size_t sql_length = strlen(literal) + 64;
    char *sql = malloc(sql_length);
    if (!sql) {
        free(literal);
        return false;
    }
    snprintf(sql, sql_length, "CREATE VIEW recons_stars AS SELECT * FROM read_parquet(%s)", literal);
    catalogue->has_recons = execute(catalogue, sql);
    free(sql);
    free(literal);
    return catalogue->has_recons;
}

bool catalog_metadata(catalog *catalogue, duckdb_result *result) {
    return duckdb_query(catalogue->connection, "SELECT * FROM catalog_metadata", result) == DuckDBSuccess;
}

static bool validate_schema(catalog *catalogue) {
    const char *names[] = {
        "id", "gaia_dr3_source_id", "name", "source_catalog", "ra_deg", "dec_deg",
        "ref_epoch_jyear", "parallax_mas", "parallax_error_mas", "distance_pc", "distance_method",
        "galactic_longitude_deg", "galactic_latitude_deg", "phot_g_mean_mag", "phot_bp_mean_mag",
        "phot_rp_mean_mag", "spectral_type",
    };
    const duckdb_type types[] = {
        DUCKDB_TYPE_VARCHAR, DUCKDB_TYPE_BIGINT, DUCKDB_TYPE_VARCHAR, DUCKDB_TYPE_VARCHAR,
        DUCKDB_TYPE_DOUBLE, DUCKDB_TYPE_DOUBLE, DUCKDB_TYPE_DOUBLE, DUCKDB_TYPE_DOUBLE,
        DUCKDB_TYPE_DOUBLE, DUCKDB_TYPE_DOUBLE, DUCKDB_TYPE_VARCHAR, DUCKDB_TYPE_DOUBLE,
        DUCKDB_TYPE_DOUBLE, DUCKDB_TYPE_DOUBLE, DUCKDB_TYPE_DOUBLE, DUCKDB_TYPE_DOUBLE,
        DUCKDB_TYPE_VARCHAR,
    };
    duckdb_result result;
    bool valid = duckdb_query(catalogue->connection, "SELECT * FROM stars LIMIT 0", &result) == DuckDBSuccess;
    for (size_t field = 0; valid && field < sizeof(names) / sizeof(names[0]); ++field) {
        bool found = false;
        for (idx_t column = 0; column < duckdb_column_count(&result); ++column) {
            if (strcmp(duckdb_column_name(&result, column), names[field]) == 0) {
                found = duckdb_column_type(&result, column) == types[field];
                break;
            }
        }
        valid = found;
    }
    duckdb_destroy_result(&result);
    if (valid) {
        valid = duckdb_query(catalogue->connection, "SELECT alias, star_id FROM aliases LIMIT 0", &result) == DuckDBSuccess;
        valid = valid && duckdb_column_type(&result, 0) == DUCKDB_TYPE_VARCHAR &&
                         duckdb_column_type(&result, 1) == DUCKDB_TYPE_VARCHAR;
        duckdb_destroy_result(&result);
    }
    if (!valid) {
        fprintf(stderr, "star-search: Parquet column names or types violate catalog schema 1\n");
    }
    return valid;
}

bool catalog_open(catalog *catalogue, const char *directory) {
    duckdb_config configuration = NULL;
    char *error = NULL;
    if (duckdb_create_config(&configuration) != DuckDBSuccess) {
        return false;
    }
    bool configured =
        duckdb_set_config(configuration, "autoinstall_known_extensions", "false") == DuckDBSuccess &&
        duckdb_set_config(configuration, "autoload_known_extensions", "false") == DuckDBSuccess &&
        duckdb_set_config(configuration, "threads", "1") == DuckDBSuccess;
    duckdb_state opened = configured ?
        duckdb_open_ext(NULL, &catalogue->database, configuration, &error) : DuckDBError;
    duckdb_destroy_config(&configuration);
    if (opened != DuckDBSuccess) {
        fprintf(stderr, "star-search: %s\n", error ? error : "cannot configure offline DuckDB");
        duckdb_free(error);
        return false;
    }
    if (duckdb_connect(catalogue->database, &catalogue->connection) != DuckDBSuccess) {
        return false;
    }
    if (!execute(catalogue, "SET disabled_filesystems = 'HTTPFileSystem'") ||
        !create_view(catalogue, directory, "stars.parquet",
                     "CREATE VIEW stars AS SELECT * FROM read_parquet(", ")") ||
        !create_view(catalogue, directory, "aliases.parquet",
                     "CREATE VIEW aliases AS SELECT alias, star_id FROM read_parquet(", ")") ||
        !create_view(catalogue, directory, "catalog.json",
                     "CREATE VIEW catalog_metadata AS SELECT * FROM read_json(",
                     ", format='unstructured', columns={schema_version:'INTEGER', "
                     "catalog_version:'VARCHAR', source_catalog:'VARCHAR', selection_rules:'VARCHAR', "
                     "distance_policy:'VARCHAR', limitations:'VARCHAR', attribution:'VARCHAR', "
                     "license:'VARCHAR', is_fixture:'BOOLEAN'})")) {
        return false;
    }
    if (!create_recons_view(catalogue, directory)) {
        return false;
    }
    duckdb_result metadata;
    bool valid = catalog_metadata(catalogue, &metadata) && duckdb_row_count(&metadata) == 1;
    if (valid) {
        for (idx_t column = 0; column < duckdb_column_count(&metadata); ++column) {
            valid = valid && !duckdb_value_is_null(&metadata, column, 0);
        }
        valid = valid && duckdb_value_int32(&metadata, 0, 0) == 1;
    }
    duckdb_destroy_result(&metadata);
    if (!valid) {
        fprintf(stderr, "star-search: incomplete manifest or unsupported catalog schema\n");
        return false;
    }
    return validate_schema(catalogue);
}

void catalog_close(catalog *catalogue) {
    if (catalogue->connection) {
        duckdb_disconnect(&catalogue->connection);
    }
    if (catalogue->database) {
        duckdb_close(&catalogue->database);
    }
}

static bool prepared_query(catalog *catalogue, const char *sql, const char *term,
                           int64_t count, duckdb_result *result) {
    duckdb_prepared_statement statement = NULL;
    bool success = duckdb_prepare(catalogue->connection, sql, &statement) == DuckDBSuccess;
    if (success) {
        success = (term ? duckdb_bind_varchar(statement, 1, term) :
                         duckdb_bind_int64(statement, 1, count)) == DuckDBSuccess;
    }
    if (success) {
        success = duckdb_execute_prepared(statement, result) == DuckDBSuccess;
    }
    if (!success) {
        const char *error = statement ? duckdb_prepare_error(statement) : NULL;
        fprintf(stderr, "star-search: query failed%s%s\n", error ? ": " : "", error ? error : "");
    }
    duckdb_destroy_prepare(&statement);
    return success;
}

static bool staged_lookup(catalog *catalogue, const char *term, const char *columns,
                          duckdb_result *result) {
    const char *conditions[] = {
        "id = $1",
        "lower(name) = lower($1) OR id IN (SELECT star_id FROM aliases WHERE lower(alias) = lower($1))",
        "contains(lower(name), lower($1)) OR id IN "
        "(SELECT star_id FROM aliases WHERE contains(lower(alias), lower($1)))",
    };
    char sql[2048];
    for (size_t stage = 0; stage < sizeof(conditions) / sizeof(conditions[0]); ++stage) {
        snprintf(sql, sizeof(sql), "SELECT %s, count(*) OVER () AS match_count "
                 "FROM stars WHERE %s ORDER BY id LIMIT 10", columns, conditions[stage]);
        if (!prepared_query(catalogue, sql, term, 0, result)) {
            return false;
        }
        if (duckdb_row_count(result) || stage == 2) {
            return true;
        }
        duckdb_destroy_result(result);
        memset(result, 0, sizeof(*result));
    }
    return true;
}

bool catalog_lookup(catalog *catalogue, const char *term, bool coordinates, duckdb_result *result) {
    return staged_lookup(catalogue, term, coordinates ? coordinate_columns : star_columns, result);
}

bool catalog_render_lookup(catalog *catalogue, const char *term, duckdb_result *result) {
    /* Render inputs added after schema 1 shipped are optional: older catalogs
     * (and the synthetic fixture built before them) simply yield NULLs. */
    static const char *optional[][2] = {
        {"teff_k", "DOUBLE"}, {"bp_rp", "DOUBLE"}, {"absolute_v_mag", "DOUBLE"},
        {"phot_variable_flag", "VARCHAR"},
    };
    duckdb_result schema;
    if (duckdb_query(catalogue->connection, "SELECT * FROM stars LIMIT 0", &schema) != DuckDBSuccess) {
        duckdb_destroy_result(&schema);
        return false;
    }
    char columns[1024] = "id, gaia_dr3_source_id, name, spectral_type, phot_g_mean_mag, parallax_mas";
    for (size_t field = 0; field < sizeof(optional) / sizeof(optional[0]); ++field) {
        bool present = false;
        for (idx_t column = 0; column < duckdb_column_count(&schema); ++column) {
            present = present || strcmp(duckdb_column_name(&schema, column), optional[field][0]) == 0;
        }
        size_t used = strlen(columns);
        if (present) {
            snprintf(columns + used, sizeof(columns) - used, ", %s", optional[field][0]);
        } else {
            snprintf(columns + used, sizeof(columns) - used, ", NULL::%s AS %s",
                     optional[field][1], optional[field][0]);
        }
    }
    duckdb_destroy_result(&schema);
    return staged_lookup(catalogue, term, columns, result);
}

bool catalog_nearest(catalog *catalogue, int64_t count, duckdb_result *result) {
    char sql[1024];
    snprintf(sql, sizeof(sql), "SELECT %s FROM stars WHERE distance_pc IS NOT NULL "
             "AND distance_pc > 0 AND isfinite(distance_pc) ORDER BY distance_pc, id LIMIT $1", star_columns);
    return prepared_query(catalogue, sql, NULL, count, result);
}

bool catalog_recons_nearest(catalog *catalogue, int64_t count, duckdb_result *result) {
    if (!catalogue->has_recons) {
        fprintf(stderr, "star-search: RECONS data is unavailable; set STAR_SEARCH_RECONS_DATA\n");
        return false;
    }
    const char *sql =
        "SELECT id, is_recons_entry, system_rank, cns_name, component, common_name, "
        "ra_hms, dec_dms, ra_deg, dec_deg, ref_epoch_jyear, parallax_arcsec, "
        "parallax_error_mas, distance_pc, distance_ly, proper_motion_arcsec_per_year, "
        "proper_motion_angle_deg, proper_motion_reference, spectral_type, v_mag, v_mag_flag, "
        "v_mag_reference, absolute_mag, mass_solar, mass_estimate_flag, notes, x_pc, y_pc, z_pc, "
        "galactic_longitude_deg, galactic_latitude_deg, source_catalog "
        "FROM recons_stars WHERE system_rank <= $1 ORDER BY system_rank, cns_name, component, id";
    return prepared_query(catalogue, sql, NULL, count, result);
}

bool catalog_recons_lookup(catalog *catalogue, const char *term, duckdb_result *result) {
    if (!catalogue->has_recons) {
        fprintf(stderr, "star-search: RECONS data is unavailable; set STAR_SEARCH_RECONS_DATA\n");
        return false;
    }
    const char *sql =
        "SELECT id, cns_name, common_name, component, system_rank, is_recons_entry, "
        "ra_hms, dec_dms, ra_deg, dec_deg, ref_epoch_jyear, parallax_arcsec, "
        "parallax_error_mas, distance_pc, distance_ly, proper_motion_arcsec_per_year, "
        "proper_motion_angle_deg, proper_motion_reference, spectral_type, v_mag, v_mag_flag, "
        "v_mag_reference, absolute_mag, mass_solar, mass_estimate_flag, notes, x_pc, y_pc, z_pc, "
        "galactic_longitude_deg, galactic_latitude_deg, source_catalog, "
        "count(*) OVER () AS match_count FROM recons_stars WHERE id = $1 OR "
        "contains(lower(cns_name), lower($1)) OR "
        "contains(lower(cns_name || ' ' || coalesce(component, '')), lower($1)) OR "
        "contains(lower(coalesce(common_name, '')), lower($1)) ORDER BY system_rank, id LIMIT 10";
    return prepared_query(catalogue, sql, term, 0, result);
}