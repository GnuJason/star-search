#
# spec file for package star-search
#
# Copyright (c) 2026 Jason
#
# All modifications and additions to the file contributed by third parties
# are copyrighted by their respective owners.
#
# Please submit bugfixes or comments via https://bugs.opensuse.org/
#

Name:           star-search
Version:        1.0
Release:        1%{?dist}
Summary:        CLI tool for nearest-star catalog exploration and rendering
License:        GPL-3.0-or-later
URL:            https://starsearch.online
Source0:        star-search-1.0.tar.gz
Group:          Productivity/Scientific/Astronomy

BuildRequires:  cmake >= 3.20
BuildRequires:  gcc
BuildRequires:  pkgconfig
BuildRequires:  pkgconfig(libcjson)
BuildRequires:  pkgconfig(libcurl)

%description
star-search is a scientific command-line tool for exploring the catalog of
nearby stars. It provides catalog queries, nearest-star listings, coordinate
conversions, and deterministic star-portrait rendering driven by a C + GLSL
shader evaluated on the CPU.

Catalog lookups are served by the star-search HTTP API (default
https://starsearch.online, overridable with STAR_SEARCH_API_URL), so network
access is required for queries; portraits are rendered locally. This package
contains the CLI and its documentation only, no datasets, website, or
generated portraits.

%prep
%setup -q -n star-search-1.0

%build
# Explicit cmake calls keep the spec portable; on openSUSE the %%cmake /
# %%cmake_build / %%cmake_install macros may be substituted.
cmake -B build -S . \
      -DCMAKE_INSTALL_PREFIX=%{_prefix} \
      -DCMAKE_INSTALL_DOCDIR=%{_docdir}/%{name} \
      -DCMAKE_BUILD_TYPE=RelWithDebInfo \
      -DBUILD_TESTING=OFF
cmake --build build %{?_smp_mflags}

%install
DESTDIR=%{buildroot} cmake --install build

%files
# README.md and catalog-contract.md are installed into the doc dir by CMake,
# so the directory is owned here instead of re-listed with %%doc.
%license COPYING
%{_bindir}/star-search
%{_datadir}/star-search/
%{_docdir}/%{name}/
%{_mandir}/man1/star-search.1*

%changelog
* Wed Sep 30 2026 Jason <jason@starsearch.online> - 1.0-1
- Initial package for openSUSE devel submission (version 1.0).
- Catalog backend switched to the star-search HTTP API (libcurl + cJSON);
  the base URL is configurable via STAR_SEARCH_API_URL and defaults to
  https://starsearch.online. Portrait rendering remains local.
- Removed the DuckDB build and runtime dependency; the package now depends
  only on libcurl and libcjson, both available in openSUSE Factory.
- An optional local (offline) catalog backend is planned for a future
  release and will ship separately so this package stays dependency-light.
- Pure CLI: datasets, the web front-end, and generated portraits are not
  included in the source tarball.
