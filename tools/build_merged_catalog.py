#!/usr/bin/env python3
"""Positional cross-match of the RECONS nearest-systems table against Gaia DR3.

Inputs (both produced by the other ``tools/`` scripts):

* ``gaia_datasets/recons_nearest.parquet`` -- 142 stellar/substellar
  components of the RECONS 100 nearest systems (positions J2000, epoch 2000.0,
  ground-based/HST parallaxes, spectral types, common names).
* ``gaia_datasets/gaia_dr3_subset.parquet`` -- Gaia DR3 sources with
  ``parallax > 40 mas`` (positions ICRS, epoch 2016.0).

Cross-match algorithm
---------------------
1. Every RECONS component position is propagated from J2000.0 to 2016.0 with
   the RECONS proper motion (``pmra`` already includes ``cos(dec)``). Nearby
   stars move a lot -- Barnard's Star travels ~166 arcsec in 16 years -- so
   this step is essential.
2. Gaia sources within ``--radius`` arcsec (default 30) of the propagated
   position are positional candidates.
3. Candidates whose parallax differs from the RECONS parallax by more than
   ``--parallax-tolerance`` (default 20 %) are rejected; they are logged in the
   merge report as ``rejected_parallax``.
4. The remaining (RECONS component, Gaia source) pairs are resolved to a
   one-to-one assignment. Pairs are ranked by angular separation, then by the
   |V - G| magnitude difference; the latter separates close binaries whose
   RECONS components share a single system coordinate (e.g. GJ 65 A/B). Any
   component that had more than one surviving candidate is flagged
   ``ambiguous`` in the report even though it received a best match.

Merge rules (per the project directive)
---------------------------------------
* RECONS overrides Gaia for: the parallax when the RECONS parallax error is
  smaller (rare -- Gaia is typically 10-50x more precise), the spectral type
  whenever RECONS has one (Gaia DR3 has none), and the name whenever RECONS
  has a common name or CNS/GJ designation.
* Gaia fills everything RECONS lacks: photometry (G/BP/RP), astrophysical
  parameters (Teff, logg, [M/H]), precise proper motions, radial velocities,
  RUWE and variability flags. Positions for matched rows are Gaia's (epoch
  2016.0); RECONS-only rows keep their propagated 2016.0 position.
* Every merged row carries provenance columns (``source_of_parallax``,
  ``source_of_spectral_type``, ``source_of_name``, ``source_of_position``,
  ``source_of_proper_motion``, ``gaia_source_id``, ``recons_name``,
  ``match_separation_arcsec``, ``match_status``).

Outputs
-------
* ``gaia_datasets/merged_catalog.parquet`` -- one row per star/brown dwarf
  (schema: ``MERGED_SCHEMA`` here, documented in docs/data-schemas.md).
* ``gaia_datasets/merge_report.md`` -- counts, ambiguous/unmatched/rejected
  lists and the largest RECONS/Gaia parallax disagreements.

Usage::

    .venv/bin/python tools/build_merged_catalog.py \
        --recons gaia_datasets/recons_nearest.parquet \
        --gaia gaia_datasets/gaia_dr3_subset.parquet \
        --output gaia_datasets/merged_catalog.parquet \
        --report gaia_datasets/merge_report.md
"""

import argparse
import json
import math
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

LIGHT_YEARS_PER_PARSEC = 3.2615637771674336
TARGET_EPOCH = 2016.0
DEFAULT_RADIUS_ARCSEC = 30.0
DEFAULT_PARALLAX_TOLERANCE = 0.20
DEFAULT_WIDE_RADIUS_ARCSEC = 60.0
MATCHED_STATUSES = ("matched", "matched_parallax_conflict")

MERGED_SCHEMA = pa.schema([
    # identity ------------------------------------------------------------
    pa.field("id", pa.string(), nullable=False),          # gaia-dr3:<sid> | recons:<...>
    pa.field("primary_name", pa.string(), nullable=False),
    pa.field("common_name", pa.string()),
    pa.field("recons_name", pa.string()),                 # "GJ 65 A" (cns_name + component)
    pa.field("recons_id", pa.string()),
    pa.field("recons_system_rank", pa.int32()),
    pa.field("recons_system_name", pa.string()),
    pa.field("component", pa.string()),
    pa.field("lhs_id", pa.string()),
    pa.field("gaia_source_id", pa.int64()),
    pa.field("gaia_designation", pa.string()),
    pa.field("source_of_name", pa.string(), nullable=False),
    # cross-match ---------------------------------------------------------
    # matched | matched_parallax_conflict | recons_only | gaia_only
    pa.field("match_status", pa.string(), nullable=False),
    pa.field("match_separation_arcsec", pa.float64()),
    pa.field("match_candidates", pa.int32()),
    pa.field("match_note", pa.string()),
    # astrometry ----------------------------------------------------------
    pa.field("ra_deg", pa.float64(), nullable=False),
    pa.field("dec_deg", pa.float64(), nullable=False),
    pa.field("ref_epoch_jyear", pa.float64(), nullable=False),
    pa.field("source_of_position", pa.string(), nullable=False),
    pa.field("parallax_mas", pa.float64(), nullable=False),
    pa.field("parallax_error_mas", pa.float64()),
    pa.field("source_of_parallax", pa.string(), nullable=False),
    pa.field("recons_parallax_mas", pa.float64()),
    pa.field("gaia_parallax_mas", pa.float64()),
    pa.field("parallax_discrepancy_pct", pa.float64()),
    pa.field("distance_pc", pa.float64(), nullable=False),
    pa.field("distance_ly", pa.float64(), nullable=False),
    pa.field("distance_mode", pa.string(), nullable=False),
    pa.field("x_pc", pa.float64(), nullable=False),
    pa.field("y_pc", pa.float64(), nullable=False),
    pa.field("z_pc", pa.float64(), nullable=False),
    pa.field("galactic_longitude_deg", pa.float64(), nullable=False),
    pa.field("galactic_latitude_deg", pa.float64(), nullable=False),
    pa.field("pmra_mas_per_year", pa.float64()),
    pa.field("pmdec_mas_per_year", pa.float64()),
    pa.field("source_of_proper_motion", pa.string()),
    pa.field("radial_velocity_km_s", pa.float64()),
    # physical ------------------------------------------------------------
    pa.field("spectral_type", pa.string()),
    pa.field("source_of_spectral_type", pa.string()),
    pa.field("v_mag", pa.float64()),
    pa.field("absolute_mag", pa.float64()),
    pa.field("mass_solar", pa.float64()),
    pa.field("phot_g_mean_mag", pa.float64()),
    pa.field("phot_bp_mean_mag", pa.float64()),
    pa.field("phot_rp_mean_mag", pa.float64()),
    pa.field("bp_rp", pa.float64()),
    pa.field("teff_gspphot_k", pa.float64()),
    pa.field("logg_gspphot", pa.float64()),
    pa.field("mh_gspphot", pa.float64()),
    pa.field("ruwe", pa.float64()),
    pa.field("non_single_star", pa.int32()),
    pa.field("phot_variable_flag", pa.string()),
    pa.field("planet_count", pa.int32()),
    pa.field("notes", pa.string()),
    pa.field("source_catalogs", pa.string(), nullable=False),
])


# ------------------------------------------------------------------ geometry

def propagate_position(ra_deg, dec_deg, pmra_mas_yr, pmdec_mas_yr, from_epoch, to_epoch):
    """Linear proper-motion propagation (adequate for a 16-year baseline)."""
    if pmra_mas_yr is None or pmdec_mas_yr is None:
        return ra_deg, dec_deg
    years = to_epoch - from_epoch
    dec = dec_deg + pmdec_mas_yr * years / 3.6e6
    cos_dec = math.cos(math.radians(dec_deg))
    if abs(cos_dec) < 1e-9:
        return ra_deg, max(-90.0, min(90.0, dec))
    ra = (ra_deg + pmra_mas_yr * years / 3.6e6 / cos_dec) % 360.0
    return ra, max(-90.0, min(90.0, dec))


def angular_separation_arcsec(ra1, dec1, ra2, dec2):
    """Vincenty formula on the sphere; robust at small separations."""
    ra1, dec1, ra2, dec2 = map(math.radians, (ra1, dec1, ra2, dec2))
    delta_ra = ra2 - ra1
    sin_d1, cos_d1 = math.sin(dec1), math.cos(dec1)
    sin_d2, cos_d2 = math.sin(dec2), math.cos(dec2)
    numerator = math.hypot(cos_d2 * math.sin(delta_ra),
                           cos_d1 * sin_d2 - sin_d1 * cos_d2 * math.cos(delta_ra))
    denominator = sin_d1 * sin_d2 + cos_d1 * cos_d2 * math.cos(delta_ra)
    return math.degrees(math.atan2(numerator, denominator)) * 3600.0


def _galactic(ra_deg, dec_deg):
    """ICRS -> galactic (IAU 1958 pole/centre, J2000 realisation)."""
    ra_ngp, dec_ngp, l_ncp = math.radians(192.85948), math.radians(27.12825), math.radians(122.93192)
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    sin_b = (math.sin(dec) * math.sin(dec_ngp)
             + math.cos(dec) * math.cos(dec_ngp) * math.cos(ra - ra_ngp))
    b = math.asin(max(-1.0, min(1.0, sin_b)))
    y = math.cos(dec) * math.sin(ra - ra_ngp)
    x = math.sin(dec) * math.cos(dec_ngp) - math.cos(dec) * math.sin(dec_ngp) * math.cos(ra - ra_ngp)
    l = (l_ncp - math.atan2(y, x)) % (2 * math.pi)
    return math.degrees(l), math.degrees(b)


def _xyz(ra_deg, dec_deg, distance_pc):
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    return (distance_pc * math.cos(dec) * math.cos(ra),
            distance_pc * math.cos(dec) * math.sin(ra),
            distance_pc * math.sin(dec))


# ---------------------------------------------------------------- cross-match

class _Grid:
    """Tiny equatorial grid index so the match is O(n) rather than O(n*m)."""

    def __init__(self, rows, cell_deg):
        self.cell = cell_deg
        self.buckets = {}
        for index, row in enumerate(rows):
            self.buckets.setdefault(self._key(row["ra_deg"], row["dec_deg"]), []).append(index)

    def _key(self, ra, dec):
        return int(ra // self.cell), int((dec + 90.0) // self.cell)

    def near(self, ra, dec):
        ra_cell, dec_cell = self._key(ra, dec)
        cos_dec = max(math.cos(math.radians(dec)), 0.05)
        ra_span = int(math.ceil(1.0 / cos_dec))
        n_ra = int(math.ceil(360.0 / self.cell))
        for d_dec in (-1, 0, 1):
            for d_ra in range(-ra_span, ra_span + 1):
                yield from self.buckets.get(((ra_cell + d_ra) % n_ra, dec_cell + d_dec), ())


def _group_key(recons):
    """RECONS components that share one system coordinate form a group."""
    return (recons.get("system_rank"), round(recons["ra_deg"], 6), round(recons["dec_deg"], 6))


def _mag_sort_key(value):
    return (value is None, value if value is not None else 0.0)


def cross_match(recons_rows, gaia_rows, radius_arcsec=DEFAULT_RADIUS_ARCSEC,
                parallax_tolerance=DEFAULT_PARALLAX_TOLERANCE, target_epoch=TARGET_EPOCH,
                wide_radius_arcsec=DEFAULT_WIDE_RADIUS_ARCSEC):
    """Return ``(assignments, diagnostics)``.

    ``assignments`` maps RECONS row index -> dict(gaia_index, separation,
    candidates, status, note) where status is ``matched`` or
    ``matched_parallax_conflict``. ``diagnostics`` holds the propagated
    positions, per-component candidate lists and rejected pairs for the report.

    Passes:

    1. *primary* -- candidates within ``radius_arcsec`` that pass the parallax
       gate. Components sharing one RECONS coordinate are paired with their
       candidates by brightness rank (V vs G); otherwise the closest pair wins.
    2. *wide* -- components of a shared-coordinate group that are still
       unmatched look out to ``wide_radius_arcsec`` for an unassigned source
       (RECONS quotes one coordinate for e.g. GJ 15 A/B, 35 arcsec apart).
    3. *conflict* -- a still-unmatched component whose *only* neighbour inside
       ``radius_arcsec`` failed the parallax gate is linked to it as
       ``matched_parallax_conflict`` so the same star is not listed twice; the
       Gaia parallax is used and the RECONS value is kept for reference.
    """
    search_radius = max(radius_arcsec, wide_radius_arcsec)
    grid = _Grid(gaia_rows, cell_deg=max(search_radius / 3600.0 * 2.0, 0.05))
    propagated = []
    candidate_lists = []   # accepted candidates within the primary radius
    wide_lists = []        # accepted candidates between radius and wide radius
    rejected = []          # failed the parallax gate (primary radius only)
    for r_index, recons in enumerate(recons_rows):
        ra, dec = propagate_position(
            recons["ra_deg"], recons["dec_deg"],
            recons.get("pmra_mas_per_year"), recons.get("pmdec_mas_per_year"),
            recons.get("ref_epoch_jyear") or 2000.0, target_epoch)
        propagated.append((ra, dec))
        recons_plx = recons.get("parallax_mas")
        v_mag = recons.get("v_mag")
        accepted, wide = [], []
        for g_index in grid.near(ra, dec):
            gaia = gaia_rows[g_index]
            separation = angular_separation_arcsec(ra, dec, gaia["ra_deg"], gaia["dec_deg"])
            if separation > search_radius:
                continue
            gaia_plx = gaia.get("parallax_mas")
            discrepancy = (abs(recons_plx - gaia_plx) / gaia_plx
                           if recons_plx and gaia_plx else None)
            if discrepancy is not None and discrepancy > parallax_tolerance:
                if separation <= radius_arcsec:
                    rejected.append({"recons_index": r_index, "gaia_index": g_index,
                                     "separation": separation, "discrepancy": discrepancy})
                continue
            g_mag = gaia.get("phot_g_mean_mag")
            # |V - G| is ~0 for solar-type stars and grows to ~2 for late-M
            # dwarfs; it is only used to *rank* candidates, never to reject.
            mag_term = abs(v_mag - g_mag) if v_mag is not None and g_mag is not None else 5.0
            entry = (separation, mag_term, g_index, discrepancy)
            (accepted if separation <= radius_arcsec else wide).append(entry)
        accepted.sort()
        wide.sort()
        candidate_lists.append(accepted)
        wide_lists.append(wide)

    # How many components consider each Gaia source (for the report notes).
    contested = {}
    for accepted in candidate_lists:
        for _, _, g_index, _ in accepted:
            contested[g_index] = contested.get(g_index, 0) + 1

    # Pass 1: build proposals. Shared-coordinate groups are paired by
    # brightness rank; singletons by separation then |V-G|.
    groups = {}
    for r_index, recons in enumerate(recons_rows):
        groups.setdefault(_group_key(recons), []).append(r_index)
    proposals = []  # (priority, separation, mag_term, r_index, g_index, discrepancy)
    for members in groups.values():
        union = {}
        for r_index in members:
            for separation, mag_term, g_index, discrepancy in candidate_lists[r_index]:
                union[g_index] = separation
        ranked = set()
        if len(members) > 1 and len(union) > 1:
            ordered_members = sorted(members, key=lambda i: _mag_sort_key(recons_rows[i].get("v_mag")))
            ordered_gaia = sorted(union, key=lambda g: _mag_sort_key(gaia_rows[g].get("phot_g_mean_mag")))
            ranked = set(zip(ordered_members, ordered_gaia))
        for r_index in members:
            for separation, mag_term, g_index, discrepancy in candidate_lists[r_index]:
                priority = 0 if (r_index, g_index) in ranked or not ranked else 1
                proposals.append((priority, separation, mag_term, r_index, g_index, discrepancy))
    proposals.sort(key=lambda item: (item[0], round(item[1], 3), item[2]))

    assignments = {}
    used_gaia = set()

    def assign(r_index, g_index, separation, discrepancy, status, note):
        assignments[r_index] = {"gaia_index": g_index, "separation": separation,
                                "candidates": len(candidate_lists[r_index]),
                                "discrepancy": discrepancy, "status": status, "note": note}
        used_gaia.add(g_index)

    for priority, separation, mag_term, r_index, g_index, discrepancy in proposals:
        if r_index in assignments or g_index in used_gaia:
            continue
        notes = []
        if len(candidate_lists[r_index]) > 1:
            notes.append(f"ambiguous: {len(candidate_lists[r_index])} Gaia candidates within "
                         f"{radius_arcsec:g} arcsec; resolved by brightness rank / separation")
        if contested.get(g_index, 0) > 1:
            notes.append(f"contested: Gaia source was a candidate for {contested[g_index]} "
                         f"RECONS components")
        assign(r_index, g_index, separation, discrepancy, "matched", "; ".join(notes) or None)

    # Pass 2: wide search for unmatched members of shared-coordinate groups.
    wide_proposals = []
    for members in groups.values():
        if len(members) < 2:
            continue
        for r_index in members:
            if r_index in assignments:
                continue
            for separation, mag_term, g_index, discrepancy in wide_lists[r_index]:
                wide_proposals.append((separation, mag_term, r_index, g_index, discrepancy))
    wide_proposals.sort()
    for separation, mag_term, r_index, g_index, discrepancy in wide_proposals:
        if r_index in assignments or g_index in used_gaia:
            continue
        assign(r_index, g_index, separation, discrepancy, "matched",
               f"wide pass: matched at {separation:.1f} arcsec (> {radius_arcsec:g} arcsec primary "
               f"radius) because RECONS lists one coordinate for the whole system")

    # Pass 3: link parallax conflicts instead of duplicating the star.
    conflict_lists = {}
    for item in rejected:
        conflict_lists.setdefault(item["recons_index"], []).append(item)
    for r_index, items in conflict_lists.items():
        if r_index in assignments or candidate_lists[r_index]:
            continue
        if len(items) != 1 or items[0]["gaia_index"] in used_gaia:
            continue
        item = items[0]
        assign(r_index, item["gaia_index"], item["separation"], item["discrepancy"],
               "matched_parallax_conflict",
               f"parallax conflict: RECONS {recons_rows[r_index].get('parallax_mas'):.1f} mas vs "
               f"Gaia {gaia_rows[item['gaia_index']].get('parallax_mas'):.1f} mas "
               f"({item['discrepancy'] * 100:.0f}% apart); positional match at "
               f"{item['separation']:.1f} arcsec kept, Gaia parallax used")

    diagnostics = {"propagated": propagated, "candidates": candidate_lists,
                   "wide_candidates": wide_lists, "rejected_parallax": rejected,
                   "contested": contested}
    return assignments, diagnostics


# --------------------------------------------------------------------- merge

def _clean_name(value):
    if value is None:
        return None
    value = " ".join(str(value).split())
    return value or None


def recons_display_name(recons):
    cns = _clean_name(recons.get("cns_name"))
    component = _clean_name(recons.get("component"))
    if cns and component:
        return f"{cns} {component}"
    return cns


def _finish_row(row):
    """Derive distance/XYZ/galactic values from the chosen parallax + position."""
    row["distance_pc"] = 1000.0 / row["parallax_mas"]
    row["distance_ly"] = row["distance_pc"] * LIGHT_YEARS_PER_PARSEC
    row["distance_mode"] = "inverse_parallax"
    row["x_pc"], row["y_pc"], row["z_pc"] = _xyz(row["ra_deg"], row["dec_deg"], row["distance_pc"])
    if row.get("galactic_longitude_deg") is None or row.get("galactic_latitude_deg") is None:
        row["galactic_longitude_deg"], row["galactic_latitude_deg"] = _galactic(
            row["ra_deg"], row["dec_deg"])
    return row


def _base_row():
    return {field.name: None for field in MERGED_SCHEMA}


def merge_rows(recons_rows, gaia_rows, assignments, diagnostics):
    merged = []
    matched_gaia = {}
    for r_index, assignment in assignments.items():
        matched_gaia[assignment["gaia_index"]] = r_index

    # RECONS components (matched or not) -----------------------------------
    for r_index, recons in enumerate(recons_rows):
        row = _base_row()
        assignment = assignments.get(r_index)
        gaia = gaia_rows[assignment["gaia_index"]] if assignment else None
        recons_name = recons_display_name(recons)
        common_name = _clean_name(recons.get("common_name"))

        row.update({
            "common_name": common_name,
            "recons_name": recons_name,
            "recons_id": recons["id"],
            "recons_system_rank": recons.get("system_rank"),
            "recons_system_name": _clean_name(recons.get("system_name")),
            "component": _clean_name(recons.get("component")),
            "lhs_id": _clean_name(recons.get("lhs_id")),
            "primary_name": common_name or recons_name or recons["id"],
            "source_of_name": "recons_common_name" if common_name else "recons_cns_name",
            "recons_parallax_mas": recons.get("parallax_mas"),
            "spectral_type": _clean_name(recons.get("spectral_type")),
            "source_of_spectral_type": "recons" if _clean_name(recons.get("spectral_type")) else None,
            "v_mag": recons.get("v_mag"),
            "absolute_mag": recons.get("absolute_mag"),
            "mass_solar": recons.get("mass_solar"),
            "planet_count": recons.get("planet_count"),
            "notes": _clean_name(recons.get("notes")),
        })

        recons_plx = recons.get("parallax_mas")
        recons_plx_err = recons.get("parallax_error_mas")
        if gaia is not None:
            gaia_plx = gaia.get("parallax_mas")
            gaia_plx_err = gaia.get("parallax_error_mas")
            row.update({
                "id": gaia["id"],
                "gaia_source_id": gaia["gaia_dr3_source_id"],
                "gaia_designation": gaia.get("designation"),
                "match_status": assignment["status"],
                "match_separation_arcsec": assignment["separation"],
                "match_candidates": assignment["candidates"],
                "match_note": assignment["note"],
                "ra_deg": gaia["ra_deg"],
                "dec_deg": gaia["dec_deg"],
                "ref_epoch_jyear": gaia.get("ref_epoch_jyear") or TARGET_EPOCH,
                "source_of_position": "gaia",
                "gaia_parallax_mas": gaia_plx,
                "parallax_discrepancy_pct": (
                    abs(recons_plx - gaia_plx) / gaia_plx * 100.0
                    if recons_plx and gaia_plx else None),
                "pmra_mas_per_year": gaia.get("pmra_mas_per_year"),
                "pmdec_mas_per_year": gaia.get("pmdec_mas_per_year"),
                "source_of_proper_motion": "gaia",
                "radial_velocity_km_s": gaia.get("radial_velocity_km_s"),
                "phot_g_mean_mag": gaia.get("phot_g_mean_mag"),
                "phot_bp_mean_mag": gaia.get("phot_bp_mean_mag"),
                "phot_rp_mean_mag": gaia.get("phot_rp_mean_mag"),
                "bp_rp": gaia.get("bp_rp"),
                "teff_gspphot_k": gaia.get("teff_gspphot_k"),
                "logg_gspphot": gaia.get("logg_gspphot"),
                "mh_gspphot": gaia.get("mh_gspphot"),
                "ruwe": gaia.get("ruwe"),
                "non_single_star": gaia.get("non_single_star"),
                "phot_variable_flag": gaia.get("phot_variable_flag"),
                "galactic_longitude_deg": gaia.get("galactic_longitude_deg"),
                "galactic_latitude_deg": gaia.get("galactic_latitude_deg"),
                "source_catalogs": "RECONS+Gaia DR3",
            })
            if gaia.get("pmra_mas_per_year") is None or gaia.get("pmdec_mas_per_year") is None:
                row["pmra_mas_per_year"] = recons.get("pmra_mas_per_year")
                row["pmdec_mas_per_year"] = recons.get("pmdec_mas_per_year")
                row["source_of_proper_motion"] = "recons"
            # Parallax: RECONS wins only when its formal error is smaller.
            recons_better = (recons_plx is not None and recons_plx_err is not None
                             and assignment["status"] == "matched"
                             and (gaia_plx is None or gaia_plx_err is None
                                  or recons_plx_err < gaia_plx_err))
            if recons_better or gaia_plx is None:
                row.update({"parallax_mas": recons_plx, "parallax_error_mas": recons_plx_err,
                            "source_of_parallax": "recons"})
            else:
                row.update({"parallax_mas": gaia_plx, "parallax_error_mas": gaia_plx_err,
                            "source_of_parallax": "gaia"})
        else:
            ra, dec = diagnostics["propagated"][r_index]
            candidates = len(diagnostics["candidates"][r_index])
            rejected = [item for item in diagnostics["rejected_parallax"]
                        if item["recons_index"] == r_index]
            note = None
            if rejected:
                note = (f"{len(rejected)} Gaia source(s) within radius rejected on parallax "
                        f"(max discrepancy {max(r['discrepancy'] for r in rejected) * 100:.0f}%)")
            elif candidates:
                note = ("only positional candidate assigned to a sibling component "
                        "(unresolved or saturated in Gaia DR3)")
            row.update({
                "id": recons["id"],
                "match_status": "recons_only",
                "match_candidates": candidates,
                "match_note": note,
                "ra_deg": ra,
                "dec_deg": dec,
                "ref_epoch_jyear": TARGET_EPOCH,
                "source_of_position": "recons_propagated",
                "parallax_mas": recons_plx,
                "parallax_error_mas": recons_plx_err,
                "source_of_parallax": "recons",
                "pmra_mas_per_year": recons.get("pmra_mas_per_year"),
                "pmdec_mas_per_year": recons.get("pmdec_mas_per_year"),
                "source_of_proper_motion": "recons" if recons.get("pmra_mas_per_year") is not None else None,
                "source_catalogs": "RECONS",
            })
        merged.append(_finish_row(row))

    # Gaia-only sources -----------------------------------------------------
    for g_index, gaia in enumerate(gaia_rows):
        if g_index in matched_gaia:
            continue
        if gaia.get("parallax_mas") is None or gaia["parallax_mas"] <= 0:
            continue
        row = _base_row()
        row.update({
            "id": gaia["id"],
            "primary_name": gaia.get("designation") or f"Gaia DR3 {gaia['gaia_dr3_source_id']}",
            "gaia_source_id": gaia["gaia_dr3_source_id"],
            "gaia_designation": gaia.get("designation"),
            "source_of_name": "gaia_designation",
            "match_status": "gaia_only",
            "ra_deg": gaia["ra_deg"],
            "dec_deg": gaia["dec_deg"],
            "ref_epoch_jyear": gaia.get("ref_epoch_jyear") or TARGET_EPOCH,
            "source_of_position": "gaia",
            "parallax_mas": gaia["parallax_mas"],
            "parallax_error_mas": gaia.get("parallax_error_mas"),
            "source_of_parallax": "gaia",
            "gaia_parallax_mas": gaia["parallax_mas"],
            "pmra_mas_per_year": gaia.get("pmra_mas_per_year"),
            "pmdec_mas_per_year": gaia.get("pmdec_mas_per_year"),
            "source_of_proper_motion": "gaia" if gaia.get("pmra_mas_per_year") is not None else None,
            "radial_velocity_km_s": gaia.get("radial_velocity_km_s"),
            "phot_g_mean_mag": gaia.get("phot_g_mean_mag"),
            "phot_bp_mean_mag": gaia.get("phot_bp_mean_mag"),
            "phot_rp_mean_mag": gaia.get("phot_rp_mean_mag"),
            "bp_rp": gaia.get("bp_rp"),
            "teff_gspphot_k": gaia.get("teff_gspphot_k"),
            "logg_gspphot": gaia.get("logg_gspphot"),
            "mh_gspphot": gaia.get("mh_gspphot"),
            "ruwe": gaia.get("ruwe"),
            "non_single_star": gaia.get("non_single_star"),
            "phot_variable_flag": gaia.get("phot_variable_flag"),
            "galactic_longitude_deg": gaia.get("galactic_longitude_deg"),
            "galactic_latitude_deg": gaia.get("galactic_latitude_deg"),
            "source_catalogs": "Gaia DR3",
        })
        merged.append(_finish_row(row))

    merged.sort(key=lambda row: (row["distance_pc"], row["id"]))
    return merged


# -------------------------------------------------------------------- report

def build_report(recons_rows, gaia_rows, merged, assignments, diagnostics, parameters):
    matched = [row for row in merged if row["match_status"] in MATCHED_STATUSES]
    conflicts = [row for row in merged if row["match_status"] == "matched_parallax_conflict"]
    recons_only = [row for row in merged if row["match_status"] == "recons_only"]
    gaia_only = [row for row in merged if row["match_status"] == "gaia_only"]
    ambiguous = [row for row in matched if (row["match_candidates"] or 0) > 1]
    systems_total = len({r["system_rank"] for r in recons_rows})
    systems_matched = len({row["recons_system_rank"] for row in matched})
    plx_from_recons = sum(1 for row in matched if row["source_of_parallax"] == "recons")

    lines = [
        "# RECONS x Gaia DR3 merge report",
        "",
        f"Generated {date.today().isoformat()} by `tools/build_merged_catalog.py`.",
        "",
        "## Parameters",
        "",
        f"- match radius: {parameters['radius_arcsec']:g} arcsec around the RECONS position "
        f"propagated from J2000.0 to {parameters['target_epoch']:g} with RECONS proper motion",
        f"- parallax agreement required: within {parameters['parallax_tolerance'] * 100:.0f}% of the Gaia parallax",
        f"- inputs: `{parameters['recons']}` ({len(recons_rows)} components, {systems_total} systems), "
        f"`{parameters['gaia']}` ({len(gaia_rows)} sources)",
        "",
        "## Counts",
        "",
        "| quantity | count |",
        "|---|---:|",
        f"| merged rows written | {len(merged)} |",
        f"| RECONS components matched to Gaia DR3 | {len(matched)} / {len(recons_rows)} |",
        f"| RECONS systems with at least one Gaia match | {systems_matched} / {systems_total} |",
        f"| RECONS components without a Gaia match (`recons_only`) | {len(recons_only)} |",
        f"| Gaia DR3 sources without a RECONS counterpart (`gaia_only`) | {len(gaia_only)} |",
        f"| matches resolved from >1 candidate (`ambiguous`) | {len(ambiguous)} |",
        f"| positional candidates rejected on parallax | {len(diagnostics['rejected_parallax'])} |",
        f"| of which linked anyway as `matched_parallax_conflict` (Gaia parallax used) | {len(conflicts)} |",
        f"| matches found by the wide pass ({parameters['wide_radius_arcsec']:g} arcsec, shared-coordinate systems) | "
        f"{sum(1 for row in matched if (row['match_note'] or '').startswith('wide pass'))} |",
        f"| matched rows whose parallax comes from RECONS (smaller error) | {plx_from_recons} |",
        f"| matched rows whose parallax comes from Gaia | {len(matched) - plx_from_recons} |",
        "",
        "## RECONS components without a Gaia DR3 match",
        "",
        "Expected: stars brighter than G ~ 3 (Sirius, alpha Centauri A/B, Procyon, Altair...) "
        "are saturated or absent in Gaia DR3; unresolved close companions (e.g. B/C components "
        "sharing one system coordinate) collapse onto a single Gaia source; a few very faint "
        "brown dwarfs are below the Gaia limit.",
        "",
        "| RECONS id | name | V | sp. type | dist (pc) | note |",
        "|---|---|---:|---|---:|---|",
    ]
    for row in recons_only:
        lines.append(f"| {row['recons_id']} | {row['primary_name']} | "
                     f"{'' if row['v_mag'] is None else f'{row['v_mag']:.2f}'} | "
                     f"{row['spectral_type'] or ''} | {row['distance_pc']:.3f} | {row['match_note'] or ''} |")

    lines += ["", "## Ambiguous matches (resolved)", ""]
    if ambiguous:
        lines += ["| RECONS id | name | Gaia source_id | sep (\") | candidates | V | G |",
                  "|---|---|---|---:|---:|---:|---:|"]
        for row in ambiguous:
            lines.append(f"| {row['recons_id']} | {row['primary_name']} | {row['gaia_source_id']} | "
                         f"{row['match_separation_arcsec']:.2f} | {row['match_candidates']} | "
                         f"{'' if row['v_mag'] is None else f'{row['v_mag']:.2f}'} | "
                         f"{'' if row['phot_g_mean_mag'] is None else f'{row['phot_g_mean_mag']:.2f}'} |")
    else:
        lines.append("none")

    lines += ["", "## Parallax conflicts linked to avoid duplicates", ""]
    if conflicts:
        lines += ["| RECONS id | name | RECONS plx (mas) | Gaia source_id | Gaia plx (mas) | sep (\") | discrepancy |",
                  "|---|---|---:|---|---:|---:|---:|"]
        for row in conflicts:
            lines.append(f"| {row['recons_id']} | {row['primary_name']} | {row['recons_parallax_mas']:.2f} | "
                         f"{row['gaia_source_id']} | {row['gaia_parallax_mas']:.2f} | "
                         f"{row['match_separation_arcsec']:.2f} | {row['parallax_discrepancy_pct']:.0f}% |")
    else:
        lines.append("none")

    lines += ["", "## Positional candidates rejected on parallax", ""]
    if diagnostics["rejected_parallax"]:
        lines += ["| RECONS id | name | RECONS plx (mas) | Gaia source_id | Gaia plx (mas) | sep (\") | discrepancy |",
                  "|---|---|---:|---|---:|---:|---:|"]
        for item in diagnostics["rejected_parallax"]:
            recons = recons_rows[item["recons_index"]]
            gaia = gaia_rows[item["gaia_index"]]
            lines.append(f"| {recons['id']} | {_clean_name(recons.get('common_name')) or recons_display_name(recons)} | "
                         f"{recons.get('parallax_mas'):.2f} | {gaia['gaia_dr3_source_id']} | "
                         f"{gaia['parallax_mas']:.2f} | {item['separation']:.2f} | {item['discrepancy'] * 100:.0f}% |")
    else:
        lines.append("none")

    lines += ["", "## Largest RECONS / Gaia parallax disagreements among matches", "",
              "| RECONS id | name | RECONS plx (mas) | Gaia plx (mas) | discrepancy | parallax used |",
              "|---|---|---:|---:|---:|---|"]
    worst = sorted((row for row in matched if row["parallax_discrepancy_pct"] is not None),
                   key=lambda row: -row["parallax_discrepancy_pct"])[:15]
    for row in worst:
        lines.append(f"| {row['recons_id']} | {row['primary_name']} | {row['recons_parallax_mas']:.2f} | "
                     f"{row['gaia_parallax_mas']:.2f} | {row['parallax_discrepancy_pct']:.1f}% | "
                     f"{row['source_of_parallax']} |")

    lines += ["", "## Matched components (separation after proper-motion propagation)", "",
              "| RECONS id | name | Gaia source_id | sep (\") | plx disc. | status | note |",
              "|---|---|---|---:|---:|---|---|"]
    for row in sorted(matched, key=lambda r: (r["recons_system_rank"] or 0, r["recons_id"])):
        lines.append(f"| {row['recons_id']} | {row['primary_name']} | {row['gaia_source_id']} | "
                     f"{row['match_separation_arcsec']:.2f} | "
                     f"{'' if row['parallax_discrepancy_pct'] is None else f'{row['parallax_discrepancy_pct']:.1f}%'} | "
                     f"{row['match_status']} | {row['match_note'] or ''} |")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------- main

def build_merged_catalog(recons_path, gaia_path, output, report=None,
                         radius_arcsec=DEFAULT_RADIUS_ARCSEC,
                         parallax_tolerance=DEFAULT_PARALLAX_TOLERANCE,
                         wide_radius_arcsec=DEFAULT_WIDE_RADIUS_ARCSEC):
    recons_rows = pq.read_table(recons_path).to_pylist()
    gaia_rows = pq.read_table(gaia_path).to_pylist()
    assignments, diagnostics = cross_match(recons_rows, gaia_rows, radius_arcsec,
                                           parallax_tolerance,
                                           wide_radius_arcsec=wide_radius_arcsec)
    merged = merge_rows(recons_rows, gaia_rows, assignments, diagnostics)

    table = pa.Table.from_pylist(merged, schema=MERGED_SCHEMA)
    table.validate(full=True)
    ids = table.column("id").to_pylist()
    if len(set(ids)) != len(ids):
        raise ValueError("merged catalog has duplicate ids")
    parameters = {"recons": str(recons_path), "gaia": str(gaia_path),
                  "radius_arcsec": radius_arcsec, "wide_radius_arcsec": wide_radius_arcsec,
                  "parallax_tolerance": parallax_tolerance, "target_epoch": TARGET_EPOCH}
    counts = {status: sum(1 for row in merged if row["match_status"] == status)
              for status in ("matched", "matched_parallax_conflict", "recons_only", "gaia_only")}
    table = table.replace_schema_metadata({
        b"description": b"RECONS 100 nearest systems cross-matched with Gaia DR3 (parallax > 40 mas)",
        b"generated_on": date.today().isoformat().encode(),
        b"match_parameters": json.dumps(parameters).encode(),
        b"match_counts": json.dumps(counts).encode(),
        b"coordinate_frame": b"ICRS, epoch 2016.0 (RECONS-only rows propagated with RECONS proper motion); "
                             b"XYZ heliocentric equatorial parsecs",
        b"schema_doc": b"docs/data-schemas.md#merged_catalogparquet",
    })
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, output, compression="zstd")

    report_text = build_report(recons_rows, gaia_rows, merged, assignments, diagnostics, parameters)
    if report:
        Path(report).write_text(report_text, encoding="utf-8")
    return {"rows": table.num_rows, "counts": counts, "report": report_text,
            "ambiguous": sum(1 for row in merged if (row["match_candidates"] or 0) > 1
                             and row["match_status"] in MATCHED_STATUSES),
            "rejected_parallax": len(diagnostics["rejected_parallax"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--recons", default="gaia_datasets/recons_nearest.parquet")
    parser.add_argument("--gaia", default="gaia_datasets/gaia_dr3_subset.parquet")
    parser.add_argument("--output", default="gaia_datasets/merged_catalog.parquet")
    parser.add_argument("--report", default="gaia_datasets/merge_report.md")
    parser.add_argument("--radius", type=float, default=DEFAULT_RADIUS_ARCSEC,
                        help="match radius in arcsec (default 30)")
    parser.add_argument("--parallax-tolerance", type=float, default=DEFAULT_PARALLAX_TOLERANCE,
                        help="max |plx_recons - plx_gaia| / plx_gaia (default 0.20)")
    parser.add_argument("--wide-radius", type=float, default=DEFAULT_WIDE_RADIUS_ARCSEC,
                        help="second-pass radius for components of shared-coordinate systems (default 60)")
    args = parser.parse_args(argv)
    summary = build_merged_catalog(args.recons, args.gaia, args.output, args.report,
                                   args.radius, args.parallax_tolerance, args.wide_radius)
    counts = summary["counts"]
    print(f"Merged rows: {summary['rows']}  (matched {counts['matched']}, "
          f"parallax-conflict links {counts['matched_parallax_conflict']}, "
          f"recons_only {counts['recons_only']}, gaia_only {counts['gaia_only']}, "
          f"ambiguous {summary['ambiguous']}, rejected on parallax {summary['rejected_parallax']})")
    print(f"Catalog: {args.output}")
    if args.report:
        print(f"Report:  {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
