cmake_minimum_required(VERSION 3.20)
project(star-search VERSION 0.1.0 LANGUAGES C)

include(GNUInstallDirs)
include(CTest)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(DUCKDB_ROOT "" CACHE PATH "DuckDB C SDK directory")
find_path(DUCKDB_INCLUDE_DIR duckdb.h HINTS "${DUCKDB_ROOT}" PATH_SUFFIXES include REQUIRED)
find_library(DUCKDB_LIBRARY duckdb HINTS "${DUCKDB_ROOT}" PATH_SUFFIXES lib lib64 REQUIRED)

add_executable(star-search src/main.c src/catalog.c src/format.c)
target_include_directories(star-search PRIVATE "${DUCKDB_INCLUDE_DIR}" src)
target_link_libraries(star-search PRIVATE "${DUCKDB_LIBRARY}")
target_compile_definitions(star-search PRIVATE
    _POSIX_C_SOURCE=200809L _XOPEN_SOURCE=700
    STAR_SEARCH_VERSION="${PROJECT_VERSION}"
    STAR_SEARCH_DATA_DIR="${CMAKE_INSTALL_FULL_DATADIR}/star-search")
target_compile_options(star-search PRIVATE -Wall -Wextra -Wpedantic -Werror)

install(TARGETS star-search RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
install(FILES README.md docs/catalog-contract.md DESTINATION ${CMAKE_INSTALL_DOCDIR})
install(FILES docs/star-search.1 DESTINATION ${CMAKE_INSTALL_MANDIR}/man1)

if(BUILD_TESTING)
    find_package(Python3 REQUIRED COMPONENTS Interpreter)
    add_test(NAME catalog-contract COMMAND ${Python3_EXECUTABLE} -m unittest
        discover -s tests -p test_catalog.py -v)
    set_tests_properties(catalog-contract PROPERTIES WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
    add_test(NAME gaia-ingestion COMMAND ${Python3_EXECUTABLE} -m unittest
        discover -s tests -p test_gaia_ingestion.py -v)
    set_tests_properties(gaia-ingestion PROPERTIES WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
    add_test(NAME cli COMMAND ${Python3_EXECUTABLE} "${CMAKE_SOURCE_DIR}/tests/test_cli.py"
        $<TARGET_FILE:star-search>)
endif()