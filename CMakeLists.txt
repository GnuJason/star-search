cmake_minimum_required(VERSION 3.20)
project(star-search VERSION 0.1.0 LANGUAGES C)

include(GNUInstallDirs)
include(CTest)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(DUCKDB_ROOT "" CACHE PATH "DuckDB C SDK directory")
find_path(DUCKDB_INCLUDE_DIR duckdb.h HINTS "${DUCKDB_ROOT}" PATH_SUFFIXES include REQUIRED)
find_library(DUCKDB_LIBRARY duckdb HINTS "${DUCKDB_ROOT}" PATH_SUFFIXES lib lib64 REQUIRED)

# Vendored single-file PNG encoder (public domain / MIT); third-party code is
# built without the project's -Werror warning set.
add_library(stb_image_write STATIC src/third_party/stb_image_write_impl.c)
target_compile_options(stb_image_write PRIVATE -w)

add_executable(star-search src/main.c src/catalog.c src/format.c src/star_params.c src/render.c)
target_include_directories(star-search PRIVATE "${DUCKDB_INCLUDE_DIR}" src)
target_link_libraries(star-search PRIVATE "${DUCKDB_LIBRARY}" stb_image_write m)
# Determinism: forbid fused multiply-add contraction and value-changing float
# optimisations in the CPU shader evaluator so output bytes are reproducible.
set_source_files_properties(src/render.c src/star_params.c PROPERTIES
    COMPILE_OPTIONS "-ffp-contract=off;-fno-fast-math")
target_compile_definitions(star-search PRIVATE
    _POSIX_C_SOURCE=200809L _XOPEN_SOURCE=700
    STAR_SEARCH_VERSION="${PROJECT_VERSION}"
    STAR_SEARCH_DATA_DIR="${CMAKE_INSTALL_FULL_DATADIR}/star-search")
target_compile_options(star-search PRIVATE -Wall -Wextra -Wpedantic -Werror)

install(TARGETS star-search RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
install(FILES README.md docs/catalog-contract.md DESTINATION ${CMAKE_INSTALL_DOCDIR})
install(FILES src/shaders/star.frag src/shaders/star.vert DESTINATION ${CMAKE_INSTALL_DATADIR}/star-search/shaders)
install(FILES docs/star-search.1 DESTINATION ${CMAKE_INSTALL_MANDIR}/man1)

if(BUILD_TESTING)
    find_package(Python3 REQUIRED COMPONENTS Interpreter)
    add_test(NAME catalog-contract COMMAND ${Python3_EXECUTABLE} -m unittest
        discover -s tests -p test_catalog.py -v)
    set_tests_properties(catalog-contract PROPERTIES WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
    add_test(NAME gaia-ingestion COMMAND ${Python3_EXECUTABLE} -m unittest
        discover -s tests -p test_gaia_ingestion.py -v)
    set_tests_properties(gaia-ingestion PROPERTIES WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
    add_test(NAME recons-ingestion COMMAND ${Python3_EXECUTABLE} -m unittest
        discover -s tests -p test_recons_ingestion.py -v)
    set_tests_properties(recons-ingestion PROPERTIES WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
    add_test(NAME gaia-subset COMMAND ${Python3_EXECUTABLE} -m unittest
        discover -s tests -p test_gaia_subset.py -v)
    set_tests_properties(gaia-subset PROPERTIES WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
    add_test(NAME merged-catalog COMMAND ${Python3_EXECUTABLE} -m unittest
        discover -s tests -p test_merge_catalog.py -v)
    set_tests_properties(merged-catalog PROPERTIES WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
    add_test(NAME cli COMMAND ${Python3_EXECUTABLE} "${CMAKE_SOURCE_DIR}/tests/test_cli.py"
        $<TARGET_FILE:star-search>)
    # Keep the canonical GLSL compiling (GLSL ES 3.00) whenever the reference
    # compiler is installed (apt install glslang-tools).
    find_program(GLSLANG_VALIDATOR glslangValidator)
    if(GLSLANG_VALIDATOR)
        add_test(NAME glsl-shaders COMMAND ${GLSLANG_VALIDATOR}
            "${CMAKE_SOURCE_DIR}/src/shaders/star.vert" "${CMAKE_SOURCE_DIR}/src/shaders/star.frag")
    endif()
    add_test(NAME render COMMAND ${Python3_EXECUTABLE} "${CMAKE_SOURCE_DIR}/tests/test_render.py"
        $<TARGET_FILE:star-search>)
endif()