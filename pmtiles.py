import gzip
import io
import json
from pprint import pprint
import struct
from types import SimpleNamespace
from enum import Enum

import requests

HTTP_PARTIAL_CONTENT_SUCCESS = requests.status_codes.codes.partial_content


PMTILES_HEADER_FORMAT = '<7scQQQQQQQQQQQccccccqqcq'
PMTILES_HEADER_RANGE = range(struct.calcsize(PMTILES_HEADER_FORMAT) - 1)
PMTILES_HEADER_FIELDS = [
    'magic_number', 'version',
    'root_directory_offset', 'root_directory_length',
    'meta_data_offset', 'meta_data_length',
    'leaf_directories_offset', 'leaf_directories_length',
    'tile_data_offset', 'tile_data_length',
    'n_addressed_tiles', 'n_tile_entries', 'n_tile_contents',
    'clustered', 'internal_compression', 'tile_compression', 'tile_type', 'min_zoom', 'max_zoom',
    'min_position', 'max_position',
    'center_zoom',
    'center_position'
]

class PMTilesCompression(Enum):
    UNKNOWN = 0x00
    NONE    = 0x01
    GZIP    = 0x02
    BROTLI  = 0x03
    ZSTD    = 0x04

class PMTilesTileType(Enum):
    UNKNOWN_OR_OTHER     = 0x00
    MVT_VECTOR_TILE      = 0x01
    PNG                  = 0x02
    JPEG                 = 0x03
    WEBP                 = 0x04
    AVIF                 = 0x05
    MAPLIBRE_VECTOR_TILE = 0x06


def lat_lon_encode(value: float) -> bytes:
    value *= 10_000_000
    value = int(value)
    value_bytes_le = struct.pack('<i', value)
    return value_bytes_le


def lat_lon_decode(value_bytes_le: bytes) -> float:
    value = struct.unpack('<i', value_bytes_le)
    value /= 10_000_000
    return value


def http_range_header_from_range(some_range: range):
    range_start = some_range.start
    range_end = some_range.stop
    # Range is inclusive
    headers = {"Range": f"bytes={range_start}-{range_end}"}
    return headers


def fetch_pmtiles_header(archive_url, header_range=PMTILES_HEADER_RANGE) -> None | bytes:
    headers = http_range_header_from_range(header_range)
    response = requests.get(archive_url, headers=headers)
    if response.status_code != HTTP_PARTIAL_CONTENT_SUCCESS:
        return None
    return response.content


def decode_pmtiles_header(header_bytes: bytes):
    data = struct.unpack(PMTILES_HEADER_FORMAT, header_bytes)
    data = dict(zip(PMTILES_HEADER_FIELDS, data))
    data = SimpleNamespace(**data)
    data.internal_compression = PMTilesCompression(int.from_bytes(data.internal_compression))
    data.tile_compression = PMTilesCompression(int.from_bytes(data.tile_compression))
    data.tile_type = PMTilesTileType(int.from_bytes(data.tile_type))
    data.clustered = data.clustered == 0x01
    data.min_zoom = int.from_bytes(data.min_zoom)
    data.max_zoom = int.from_bytes(data.max_zoom)
    data.center_zoom = int.from_bytes(data.center_zoom)
    return data


def fetch_root_directory(header, url):
    root_directory_range = range(
        header.root_directory_offset,
        header.root_directory_offset + header.root_directory_length - 1
    )
    http_headers = http_range_header_from_range(root_directory_range)
    response = requests.get(url, headers=http_headers)
    if response.status_code != HTTP_PARTIAL_CONTENT_SUCCESS:
        return None
    root_directory_bytes = response.content
    return root_directory_bytes


def decode_varint_from_stream(stream):
    result = 0
    # varints are made up of 1 to 10 bytes
    for i in range(10):
        next_byte = int.from_bytes(stream.read(1))
        should_continue = (next_byte & 0x80) != 0
        contents = next_byte & 0x7F
        n_shifts = 7 * i
        result |= (contents << n_shifts)
        if not should_continue:
            break
    return result


def decode_directory(directory_bytes):
    tile_ids = []
    run_lengths = []
    lengths = []
    offsets = []

    decompressed_bytes = gzip.decompress(directory_bytes)
    stream = io.BytesIO(decompressed_bytes)
    n_entries = decode_varint_from_stream(stream)
    loop_range = range(n_entries)

    last_id = 0
    for _ in loop_range:
        delta = decode_varint_from_stream(stream)
        last_id = last_id + delta
        tile_ids.append(last_id)

    for _ in loop_range:
        run_length = decode_varint_from_stream(stream)
        run_lengths.append(run_length)

    for _ in loop_range:
        length = decode_varint_from_stream(stream)
        lengths.append(length)

    for i in loop_range:
        value = decode_varint_from_stream(stream)
        if value == 0 and i > 0:
            previous_offset = offsets[i - 1]
            previous_length = lengths[i - 1]
            offset = previous_offset + previous_length
        else:
            offset = value - 1
        offsets.append(offset)

    namespace_fields = ['n_entries', 'tile_ids', 'run_lengths', 'lengths', 'offsets']
    scope = locals()
    return SimpleNamespace(**{field: scope[field] for field in namespace_fields})


def zoom_offset(z: int):
    if z == 0:
        return 0
    four_to_the_z = 1 << (2 * z)
    return (four_to_the_z - 1) // 3


def rotate(n, x, y, rx, ry):
    if ry == 0:
        if rx == 1:
            x = n - 1 - x
            y = n - 1 - y
        return y, x
    return x, y


def hilbert_to_xy(t: int, order: int) -> (int, int):
    s = 1
    guard = 1 << order
    x = 0
    y = 0
    while s < guard:
        rx = (1 & (t // 2))
        ry = (1 & (t ^ rx))
        x, y = rotate(s, x, y, rx, ry)
        t >>= 2
        s <<= 1
    return x, y


def decode_tile_id(tile_id: int):
    z = 0
    while True:
        if z > 26:
            raise RuntimeError(f'Tile ID {tile_id} exceeds max supported range')
        next_offset = zoom_offset(z + 1)
        if tile_id < next_offset:
            break
        z += 1
    hilbert_index = tile_id - zoom_offset(z)
    x, y = hilbert_to_xy(hilbert_index, z)
    return z, x, y


if __name__ == '__main__':
    tile_archive = 'https://build.protomaps.com/20260904.pmtiles'
    header_bytes = fetch_pmtiles_header(tile_archive)
    header = decode_pmtiles_header(header_bytes)
    pprint(header)
    root_dir_bytes = fetch_root_directory(header, tile_archive)
    root_dir = decode_directory(root_dir_bytes)
    pprint(root_dir)
    for tile_id in root_dir.tile_ids:
        print(tile_id, decode_tile_id(tile_id))