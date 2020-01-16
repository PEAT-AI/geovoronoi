"""
geovoronoi – main module

Imports all necessary functions to calculate Voronoi regions from a set of coordinates on a geographic shape.
Addtionally imports some helper funcitons.

Author: Markus Konrad <markus.konrad@wzb.eu>
"""


from ._geo_voronoi import coords_to_points, points_to_coords, GeoVoronoi
# from ._geom import calculate_polygon_areas


__title__ = 'geo_voronoi'
__version__ = '0.2.0'
__author__ = 'Pascal Gula'
__license__ = 'Apache License 2.0'
