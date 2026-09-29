"""Extract the RECONS 2012 nearest-systems table into CSV and Parquet."""

import argparse
import csv
from datetime import date
from html.parser import HTMLParser
import hashlib
import json
import math
from pathlib import Path
import re
import urllib.request

import pyarrow as pa
import pyarrow.parquet as pq


SOURCE_URL = "http://recons.org/TOP100.posted.htm"
TABLE_DATE = "2012-01-01"
LIGHT_YEARS_PER_PARSEC = 3.2615637771674336
EXPECTED_RANKS = set(range(1, 101))

RECONS_SCHEMA = pa.schema([
    pa.field("id", pa.string(), nullable=False),
    pa.field("is_recons_entry", pa.bool_(), nullable=False),
    pa.field("system_rank", pa.int32(), nullable=False),
    pa.field("cns_name", pa.string(), nullable=False),
    pa.field("component", pa.string()),
    pa.field("common_name", pa.string()),
    pa.field("num_objects", pa.string()),
    pa.field("lhs_id", pa.string()),
    pa.field("ra_hms", pa.string(), nullable=False),
    pa.field("dec_dms", pa.string(), nullable=False),
    pa.field("ra_deg", pa.float64(), nullable=False),
    pa.field("dec_deg", pa.float64(), nullable=False),
    pa.field("ref_epoch_jyear", pa.float64(), nullable=False),
    pa.field("proper_motion_arcsec_per_year", pa.float64()),
    pa.field("proper_motion_angle_deg", pa.float64()),
    pa.field("proper_motion_reference", pa.string()),
    pa.field("parallax_arcsec", pa.float64(), nullable=False),
    pa.field("parallax_error_mas", pa.float64()),
    pa.field("parallax_reference", pa.string()),
    pa.field("distance_pc", pa.float64(), nullable=False),
    pa.field("distance_ly", pa.float64(), nullable=False),
    pa.field("x_pc", pa.float64(), nullable=False),
    pa.field("y_pc", pa.float64(), nullable=False),
    pa.field("z_pc", pa.float64(), nullable=False),
    pa.field("galactic_longitude_deg", pa.float64(), nullable=False),
    pa.field("galactic_latitude_deg", pa.float64(), nullable=False),
    pa.field("spectral_type", pa.string()),
    pa.field("v_mag", pa.float64()),
    pa.field("v_mag_flag", pa.string()),
    pa.field("v_mag_reference", pa.string()),
    pa.field("absolute_mag", pa.float64()),
    pa.field("mass_solar", pa.float64()),
    pa.field("mass_estimate_flag", pa.string()),
    pa.field("notes", pa.string()),
    pa.field("source_catalog", pa.string(), nullable=False),
])


class _PreformattedText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_pre = False
        self.in_link = False
        self.parts = []

    def handle_starttag(self, tag, attributes):
        if tag.lower() == "pre":
            self.in_pre = True
        elif self.in_pre and tag.lower() == "a":
            self.in_link = True

    def handle_endtag(self, tag):
        if tag.lower() == "a":
            self.in_link = False
        elif tag.lower() == "pre":
            self.in_pre = False

    def handle_data(self, data):
        if self.in_pre and not self.in_link:
            self.parts.append(data)


def _read_source(source):
    source = str(source)
    if source.startswith(("http://", "https://")):
        request = urllib.request.Request(source, headers={"User-Agent": "star-search RECONS importer"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    return Path(source).read_bytes()


def _number(value):
    match = re.match(r"^\s*(-?\d+(?:\.\d+)?)(?:\s*([A-Za-z*]+))?\s*$", value)
    if not match:
        return None, None
    number = float(match.group(1))
    return (number, match.group(2)) if math.isfinite(number) else (None, None)


def _hms_to_degrees(value):
    hours, minutes, seconds = (float(part) for part in value.split())
    if not (0 <= hours < 24 and 0 <= minutes < 60 and 0 <= seconds < 60):
        raise ValueError(f"invalid right ascension: {value}")
    return (hours + minutes / 60 + seconds / 3600) * 15


def _dms_to_degrees(value):
    degrees, minutes, seconds = value.split()
    sign = -1 if degrees.startswith("-") else 1
    absolute_degrees = abs(float(degrees))
    minutes = float(minutes)
    seconds = float(seconds)
    if not (0 <= absolute_degrees <= 90 and 0 <= minutes < 60 and 0 <= seconds < 60):
        raise ValueError(f"invalid declination: {value}")
    result = sign * (absolute_degrees + minutes / 60 + seconds / 3600)
    if abs(result) > 90:
        raise ValueError(f"invalid declination: {value}")
    return result


def _coordinates(ra_deg, dec_deg, distance_pc):
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    cos_dec = math.cos(dec)
    x = distance_pc * cos_dec * math.cos(ra)
    y = distance_pc * cos_dec * math.sin(ra)
    z = distance_pc * math.sin(dec)

    galactic_x = -0.0548755604 * cos_dec * math.cos(ra) - 0.8734370902 * cos_dec * math.sin(ra) - 0.4838350155 * math.sin(dec)
    galactic_y = 0.4941094279 * cos_dec * math.cos(ra) - 0.4448296300 * cos_dec * math.sin(ra) + 0.7469822445 * math.sin(dec)
    galactic_z = -0.8676661490 * cos_dec * math.cos(ra) - 0.1980763734 * cos_dec * math.sin(ra) + 0.4559837762 * math.sin(dec)
    longitude = math.degrees(math.atan2(galactic_y, galactic_x)) % 360
    latitude = math.degrees(math.asin(max(-1.0, min(1.0, galactic_z))))
    return x, y, z, longitude, latitude


def _star_id(cns_name, component):
    identifier = re.sub(r"[^a-z0-9]+", "-", cns_name.lower()).strip("-")
    if component:
        identifier += ":" + component.lower()
    return "recons:" + identifier


def parse_recons_html(html):
    parser = _PreformattedText()
    parser.feed(html)
    text = "".join(parser.parts)
    marker = "FORMER TOP 100 MEMBERS"
    if marker not in text:
        raise ValueError("RECONS current-list boundary is missing")
    current_list = text.split(marker, 1)[0]

    ranks = set()
    current_rank = None
    records = []
    for line in current_list.splitlines():
        rank_match = re.match(r"^\s*(\d{1,3})\.\s", line)
        if rank_match:
            current_rank = int(rank_match.group(1))
            if current_rank in EXPECTED_RANKS:
                ranks.add(current_rank)
        if current_rank not in EXPECTED_RANKS or len(line) < 55:
            continue

        ra_hms = line[34:45].strip()
        dec_dms = line[45:55].strip()
        if not re.fullmatch(r"\d{2}\s+\d{2}\s+\d{2}\.\d", ra_hms):
            continue
        if not re.fullmatch(r"[+-]\d{2}\s+\d{2}\s+\d{2}", dec_dms):
            continue

        cns_and_component = line[5:18].split()
        if not cns_and_component:
            continue
        component = None
        if cns_and_component[-1] in {"A", "B", "C", "D"}:
            component = cns_and_component.pop()
        object_fields = line[18:26].split()
        if component is None and object_fields and object_fields[0] in {"A", "B", "C", "D"}:
            component = object_fields.pop(0)
        cns_name = " ".join(cns_and_component)
        spectral_type = line[98:107].strip()
        if spectral_type.lower().startswith("planet"):
            continue

        parallax, _ = _number(line[74:82])
        if parallax is None or parallax <= 0:
            raise ValueError(f"rank {current_rank}: missing or invalid parallax for {cns_name}")
        parallax_error_arcsec, _ = _number(line[82:91])
        ra_deg = _hms_to_degrees(ra_hms)
        dec_deg = _dms_to_degrees(dec_dms)
        distance_pc = 1 / parallax
        x_pc, y_pc, z_pc, galactic_longitude, galactic_latitude = _coordinates(
            ra_deg, dec_deg, distance_pc)
        v_mag, v_mag_flag = _number(line[111:119])
        absolute_mag, _ = _number(line[119:127])
        mass_solar, mass_flag = _number(line[127:134])

        notes = line[134:154].strip() or None
        trailing_text = line[154:].strip()
        if re.search(r"\bet al\.|\b(?:19|20)\d{2}\b", trailing_text):
            notes = " ".join(part for part in (notes, trailing_text) if part) or None
            common_name = None
        else:
            common_name = trailing_text or None

        records.append({
            "id": _star_id(cns_name, component),
            "is_recons_entry": True,
            "system_rank": current_rank,
            "cns_name": cns_name,
            "component": component,
            "common_name": common_name,
            "num_objects": " ".join(object_fields) or None,
            "lhs_id": line[26:34].strip() or None,
            "ra_hms": ra_hms,
            "dec_dms": dec_dms,
            "ra_deg": ra_deg,
            "dec_deg": dec_deg,
            "ref_epoch_jyear": 2000.0,
            "proper_motion_arcsec_per_year": _number(line[58:64])[0],
            "proper_motion_angle_deg": _number(line[64:70])[0],
            "proper_motion_reference": line[70:74].strip() or None,
            "parallax_arcsec": parallax,
            "parallax_error_mas": parallax_error_arcsec * 1000 if parallax_error_arcsec is not None else None,
            "parallax_reference": line[91:98].strip() or None,
            "distance_pc": distance_pc,
            "distance_ly": distance_pc * LIGHT_YEARS_PER_PARSEC,
            "x_pc": x_pc,
            "y_pc": y_pc,
            "z_pc": z_pc,
            "galactic_longitude_deg": galactic_longitude,
            "galactic_latitude_deg": galactic_latitude,
            "spectral_type": spectral_type or None,
            "v_mag": v_mag,
            "v_mag_flag": v_mag_flag or None,
            "v_mag_reference": line[107:111].strip() or None,
            "absolute_mag": absolute_mag,
            "mass_solar": mass_solar,
            "mass_estimate_flag": mass_flag or None,
            "notes": notes,
            "source_catalog": "RECONS (100 Nearest Star Systems; 2012-01-01)",
        })

    if ranks != EXPECTED_RANKS:
        missing = sorted(EXPECTED_RANKS - ranks)
        raise ValueError(f"expected ranked systems 1-100; missing ranks: {missing}")
    identifiers = [record["id"] for record in records]
    if len(records) < len(ranks) or len(set(identifiers)) != len(identifiers):
        raise ValueError("RECONS rows are incomplete or contain duplicate component IDs")
    pa.Table.from_pylist(records, schema=RECONS_SCHEMA).validate(full=True)
    return records


def build_recons_catalog(source, parquet_output, csv_output=None):
    source_bytes = _read_source(source)
    html = source_bytes.decode("latin-1")
    records = parse_recons_html(html)
    parquet_output = Path(parquet_output)
    parquet_output.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(records, schema=RECONS_SCHEMA)
    table = table.replace_schema_metadata({
        b"source_url": SOURCE_URL.encode(),
        b"source_sha256": hashlib.sha256(source_bytes).hexdigest().encode(),
        b"source_epoch": TABLE_DATE.encode(),
        b"generated_on": date.today().isoformat().encode(),
        b"included_records": str(len(records)).encode(),
        b"excluded_planet_rows": b"planet rows are excluded; stellar and substellar components are retained",
        b"coordinate_frame": b"equatorial J2000; XYZ are heliocentric equatorial parsecs",
    })
    pq.write_table(table, parquet_output, compression="zstd")
    if csv_output is not None:
        csv_output = Path(csv_output)
        csv_output.parent.mkdir(parents=True, exist_ok=True)
        with csv_output.open("w", newline="", encoding="utf-8") as destination:
            writer = csv.DictWriter(destination, fieldnames=RECONS_SCHEMA.names,
                                    lineterminator="\n")
            writer.writeheader()
            writer.writerows(records)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", default=SOURCE_URL,
                        help="RECONS HTML file or source URL")
    parser.add_argument("--output", type=Path,
                        default=Path("gaia_datasets/recons_nearest.parquet"))
    parser.add_argument("--csv-output", type=Path,
                        help="also write normalized CSV to this path")
    arguments = parser.parse_args()
    try:
        records = build_recons_catalog(arguments.source, arguments.output,
                                       arguments.csv_output)
    except (OSError, UnicodeError, ValueError, pa.ArrowException) as error:
        parser.error(str(error))
    systems = len({record["system_rank"] for record in records})
    print(f"RECONS systems: {systems}; stellar components: {len(records)}")
    print(f"Parquet written to {arguments.output}")
    if arguments.csv_output:
        print(f"CSV written to {arguments.csv_output}")


if __name__ == "__main__":
    main()