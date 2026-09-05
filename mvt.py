from box import Box
import gzip
from google.protobuf.json_format import MessageToDict
from math import log2
from pathlib import Path
import sys
from PIL import Image, ImageDraw

from gen.vector_tile_pb2 import Tile


MVT_COMMAND_MOVE_TO = 1
MVT_COMMAND_LINE_TO = 2
MVT_COMMAND_CLOSE_PATH = 7


class Polygon:
    def __init__(self, points):
        self.points = points

    def __str__(self):
        return str(self.points)

    def __repr__(self):
        return str(self)


class TilePainter:

    def __init__(self, dimensions, background_color):
        self.canvas = Image.new("RGB", dimensions, background_color)
        self.land_color = background_color
        self.ctx = ImageDraw.Draw(self.canvas)

    def paint(self, layers, styles):
        features = layers['water']
        water_style = styles.water
        for polygon in features[0]:
            shoelace = calculate_winding_order(polygon.points)
            if shoelace < 0:
                fill = water_style.fill
            else:
                fill = self.land_color
            self.ctx.polygon(polygon.points, fill=fill)

        for geometry in features[1:]:
            for polygon in geometry:
                shoelace = calculate_winding_order(polygon.points)
                if shoelace < 0:
                    fill = '#303040'
                else:
                    fill = self.land_color
                self.ctx.polygon(polygon.points, fill=fill)

    def display_result(self):
        self.canvas.show()

    def save_result_as(self, path):
        self.canvas.save(path)


def main():
    if len(sys.argv) < 2:
        print(f'Usage: {sys.argv[0]} path/to/tile.mvt', file=sys.stderr)
        sys.exit(1)
    mvt_file = Path(sys.argv[1])
    with gzip.open(mvt_file, 'rb') as f:
        layers = extract_layers_from_mvt(f)
    painter = TilePainter((4096, 4096), '#202020')
    styles = Box({
        'water': {'fill': '#101010'}
    })
    painter.paint(layers, styles)
    painter.display_result()
    print(layers)


def extract_layers_from_mvt(mvt_stream):
    contents = mvt_stream.read()
    tile = Tile()
    tile.ParseFromString(contents)
    tile = MessageToDict(tile)
    # Allow . notation on dict keys
    tile = Box(tile)
    import json
    layers = {}
    for layer in tile.layers:
        name, features = extract_layer(layer)
        layers[name] = features
    return layers


def extract_layer(layer):
    features = []
    for feature in layer.features:
        feature_type = feature.type
        helper = feature_type_to_extractor_map.get(feature_type)
        if helper:
            extracted = helper(feature.geometry)
            print(feature)
            features.append(extracted)
        else:
            print(f'Layer {layer_name} has unsupported feature type: {feature_type}')
    return layer.name, features


def extract_polygon(geometry_commands):
    points = []
    polygons = []
    c = (0, 0)
    commands_and_parameters = iter(geometry_commands)
    while (command_and_count := next(commands_and_parameters, None)) is not None:
        command, count = decode_command(command_and_count)
        if command == MVT_COMMAND_CLOSE_PATH:
            points.append(points[0])
            polygons.append(Polygon(points))
            points = []
        else:
            for i in range(count):
                dx = zigzag_decode(next(commands_and_parameters, None))
                dy = zigzag_decode(next(commands_and_parameters, None))
                d = (dx, dy)
                p = add(c, d)
                points.append(p)
                c = p
    return polygons


feature_type_to_extractor_map = {
    'POLYGON': extract_polygon
}


def calculate_winding_order(points: list[tuple[int, int]]) -> int:
    """
    Calculate the shoelace sum of a polygon, where positive Y is down. Positive shoelace sums
    indicate exteriors, negative indicate interiors, zero indicates a denegerate polygon

    The polygon must be closed, meaning the first point and last point in the list are identical
    """
    shoelace_sum = 0

    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        shoelace_sum += (x2 - x1) * (y2 + y1)
    return shoelace_sum


def add(a, b):
    ax, ay = a
    bx, by = b
    return (ax + bx, ay + by)


def zigzag_decode(p):
    return (p >> 1) ^ (-(p & 1))


def decode_command(command_and_count):
    command = command_and_count & 7
    count = command_and_count >> 3
    return (command, count)


if __name__ == '__main__':
    main()

# def to_size(p, extent, desired_size):
#     x, y = p
#     log2_extent = int(log2(extent))
#     log2_desired = int(log2(desired_size))
#     d = log2_extent - log2_desired
#     x >>= d
#     y >>= d
#     return (x, y)

