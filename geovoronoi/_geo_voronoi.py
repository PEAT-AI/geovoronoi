"""
Functions to create Voronoi regions from points inside a geographic area.

"shapely" refers to the [Shapely Python package for computational geometry](http://toblerity.org/shapely/index.html).

Author: Markus Konrad <markus.konrad@wzb.eu>
"""

import logging

import numpy as np
from scipy.spatial import Voronoi
from scipy.spatial.distance import cdist
from shapely.geometry import LineString  # , asPoint
from shapely.ops import polygonize, cascaded_union

from ._geom import calc_diagonal  # , polygon_around_center


logger = logging.getLogger("geovoronoi")
logger.addHandler(logging.NullHandler())


# def coords_to_points(coords):
#     """Convert a NumPy array of 2D coordinates `coords` to a list of shapely Point objects"""
#     return list(map(asPoint, coords))


# def points_to_coords(pts):
#     """Convert a list of shapely Point objects to a NumPy array of 2D coordinates `coords`"""
#     return np.array([p.coords[0] for p in pts])


class GeoVoronoi:
    """ Voronoi used with GeoData

    Parameters
    ----------
    points : ndarray of floats, shape (npoints, 2)
        Coordinates of points to construct a GeoVoronoi diagram from
    shape : BaseGeometry
        Input Shapely base geometry used to enclose the voronoi diagram

    Attributes
    ----------
    points :
    regions :
    points_to_regions:

    Raises
    ------
    ValueError
        If there are duplicates in `points`.
        If the provided `radius` is not consistent with `points`.
    """

    def __init__(self, points, shape):
        """
        Initializes the object and starts the computation of the Voronoi
        diagram.

        points : The generator points of the Voronoi diagram assumed to be
         all on the sphere with radius supplied by the radius parameter and
         center supplied by the center parameter.
        radius : The radius of the sphere. Will default to 1 if not supplied.
        center : The center of the sphere. Will default to the origin if not
         supplied.
        """

        self.points = points
        self.shape = shape
        self.regions = None
        self.points_to_regions = [None] * len(points)

        self._calc_all()

    def plot(self):
        pass

    def _calc_all(self):
        # 1. compute the original Voronoi Diagram
        _voronoi = Voronoi(self.points)

        # 2. complete the vertices with "far points"
        self._calc_far_points(_voronoi)

    def _calc_far_points(self, voronoi, shape):

        center = voronoi.points.mean(axis=0)
        max_distance = calc_diagonal(shape)

        # both ridge_points and ridge_vertices of list of tuple of points
        for ridge_2_points_idx, ridge_2_vertice_idx in zip(
            voronoi.ridge_points, voronoi.ridge_vertices
        ):
            ridge_2_vertice_idx = np.asarray(ridge_2_vertice_idx)
            if np.all(ridge_2_vertice_idx):
                # we have a finite line here
                # TODO(pg): see if we do anything special here
                pass
            else:
                # one missing "infinite" vertices that we will approximate as
                # far point to be able to construct a polygon that will enclose
                # the input shape in the proper direction

                # index of the finitite vertex
                i = ridge_2_vertice_idx[ridge_2_vertice_idx >= 0][0]

                # tangent of the ridge associated input points
                tangent = (
                    voronoi.points[ridge_2_points_idx[1]] - voronoi.points[ridge_2_points_idx[0]]
                )


def geo_voronoi(
    coords,
    geo_shape,
    shapes_from_diff_with_min_area=None,
    accept_n_coord_duplicates=None,
    return_unassigned_points=False,
):
    """
    Calculate Voronoi regions from NumPy array of 2D coordinates `coord` that lie within a shape `geo_shape`. Setting
    `shapes_from_diff_with_min_area` fixes rare errors where the Voronoi shapes do not fully cover `geo_shape`. Set this
    to a small number that indicates the minimum valid area of "fill up" Voronoi region shapes.
    Set `accept_n_coord_duplicates` to accept exactly this number of points with exactly the same coordinates. Such
    duplicates will belong to the same Voronoi region. If set to `None` then any number of duplicate coordinates is
    accepted. Set `return_unassigned_points` to True to additionally return a list of shapely Point objects that could
    not be assigned to any Voronoi region.

    This function returns the following values in a tuple:
    1. `poly_shapes`: a list of shapely Polygon/MultiPolygon objects that represent the generated Voronoi regions
    2. `points`: the input coordinates converted to a list of shapely Point objects
    3. `poly_to_pt_assignments`: a nested list that for each Voronoi region in `poly_shapes` contains a list of indices
       into `points` (or `coords`) that represent the points that belong to this Voronoi region. Usually, this is only
       a single point. However, in case of duplicate points (e.g. both or more points have exactly the same coordinates)
       then all these duplicate points are listed for the respective Voronoi region.
    4. optional if `return_unassigned_points` is True: a list of points that could not be assigned to any Voronoi region
    """

    logger.info("running Voronoi tesselation for %d points" % len(coords))
    vor = Voronoi(coords)
    logger.info("generated %d Voronoi regions" % (len(vor.regions) - 1))

    logger.info("generating Voronoi polygon lines")
    poly_lines = polygon_lines_from_voronoi(vor, geo_shape)

    logger.info("generating Voronoi polygon shapes")
    poly_shapes = polygon_shapes_from_voronoi_lines(
        poly_lines, geo_shape, shapes_from_diff_with_min_area=shapes_from_diff_with_min_area
    )

    logger.info("assigning %d points to %d Voronoi polygons" % (len(coords), len(poly_shapes)))
    points = coords_to_points(coords)
    poly_to_pt_assignments, unassigned_pts = assign_points_to_voronoi_polygons(
        points,
        poly_shapes,
        accept_n_coord_duplicates=accept_n_coord_duplicates,
        return_unassigned_points=True,
        coords=coords,
    )

    if return_unassigned_points:
        return poly_shapes, points, poly_to_pt_assignments, list(unassigned_pts)
    else:
        return poly_shapes, points, poly_to_pt_assignments


def polygon_lines_from_voronoi(vor, geo_shape, return_only_poly_lines=True):
    """
    Takes a scipy Voronoi result object `vor` (see [1]) and a shapely Polygon `geo_shape` the represents the geographic
    area in which the Voronoi regions shall be placed. Calculates the following three lists:
    1. Polygon lines of the Voronoi regions. These can be used to generate all Voronoi region polygons via
       `polygon_shapes_from_voronoi_lines`.
    2. Loose ridges of Voronoi regions.
    3. Far points of loose ridges of Voronoi regions.

    If `return_only_poly_lines` is True, only the first list is returned, otherwise a tuple of all three lists is
    returned.

    Calculation of Voronoi region polygon lines taken and adopted from [2].

    [1]: https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.Voronoi.html#scipy.spatial.Voronoi
    [2]: https://github.com/scipy/scipy/blob/v1.0.0/scipy/spatial/_plotutils.py
    """

    xmin, ymin, xmax, ymax = geo_shape.bounds
    xrange = xmax - xmin
    yrange = ymax - ymin
    max_dim_extend = max(xrange, yrange)

    center = vor.points.mean(axis=0)
    # center = np.array(geo_shape.centroid)

    # generate lists of full polygon lines, loose ridges and far points of loose ridges from scipy Voronoi result object
    poly_lines = []
    loose_ridges = []
    far_points = []
    for pointidx, simplex in zip(vor.ridge_points, vor.ridge_vertices):
        simplex = np.asarray(simplex)
        if np.all(simplex >= 0):  # full finite polygon line
            poly_lines.append(LineString(vor.vertices[simplex]))
        else:  # "loose ridge": contains infinite Voronoi vertex
            i = simplex[simplex >= 0][0]  # finite end Voronoi vertex

            t = vor.points[pointidx[1]] - vor.points[pointidx[0]]  # tangent
            t /= np.linalg.norm(t)
            n = np.array([-t[1], t[0]])  # normal

            midpoint = vor.points[pointidx].mean(axis=0)
            direction = np.sign(np.dot(midpoint - center, n)) * n
            direction = direction / np.linalg.norm(direction)  # to unit vector
            far_point = vor.vertices[i] + direction * max_dim_extend

            loose_ridges.append(LineString(np.vstack((vor.vertices[i], far_point))))
            far_points.append(far_point)

    # TODO(pg): keep track of the vertices where one end was a far_points
    # TODO(pg): once we have computed the far_points, we can complete the region that includes some -1
    # it will be done by getting the far_points associated to the vertices that are not in a well formed vertices
    # TODO(pg): polygon can then be built !

    # TODO(pg): as a bonus, we can use the point_region to easily identify which input point belongs to which region!

    #
    # confine the infinite Voronoi regions by constructing a "hull" from loose ridge far points around the centroid of
    # the geographic area
    #

    # first append the loose ridges themselves
    for l in loose_ridges:
        poly_lines.append(l)

    # now create the "hull" of far points: `far_points_hull`
    far_points = np.array(far_points)
    far_points_hull = polygon_around_center(far_points, center)

    if far_points_hull is None:
        raise RuntimeError("no polygonal hull of far points could be created")

    # sometimes, this hull does not completely encompass the geographic area `geo_shape`
    if not far_points_hull.contains(geo_shape):  # if that's the case, merge it by taking the union
        far_points_hull = far_points_hull.union(geo_shape)

    # now add the lines that make up `far_points_hull` to the final `poly_lines` list
    far_points_hull_coords = far_points_hull.exterior.coords
    for i, pt in list(enumerate(far_points_hull_coords))[1:]:
        poly_lines.append(LineString((far_points_hull_coords[i - 1], pt)))
    poly_lines.append(LineString((far_points_hull_coords[-1], far_points_hull_coords[0])))

    if return_only_poly_lines:
        return poly_lines
    else:
        return poly_lines, loose_ridges, far_points


def polygon_shapes_from_voronoi_lines(
    poly_lines, geo_shape=None, shapes_from_diff_with_min_area=None
):
    """
    Form shapely Polygons objects from a list of shapely LineString objects in `poly_lines` by using
    [`polygonize`](http://toblerity.org/shapely/manual.html#shapely.ops.polygonize). If `geo_shape` is not None, then
    the intersection between any generated polygon and `geo_shape` is taken in case they overlap (i.e. the Voronoi
    regions at the border are "cut" to the `geo_shape` polygon that represents the geographic area holding the
    Voronoi regions). Setting `shapes_from_diff_with_min_area` fixes rare errors where the Voronoi shapes do not fully
    cover `geo_shape`. Set this to a small number that indicates the minimum valid area of "fill up" Voronoi region
    shapes.
    Returns a list of shapely Polygons objects.
    """

    # generate shapely Polygon objects from the LineStrings of the Voronoi shapes in `poly_lines`
    poly_shapes = []
    for p in polygonize(poly_lines):
        if geo_shape is not None and not geo_shape.contains(
            p
        ):  # if `geo_shape` contains polygon `p`,
            p = p.intersection(geo_shape)  # intersect it with `geo_shape` (i.e. "cut" it)

        poly_shapes.append(p)

    # TODO(pg): check that geo_shape is contained in the union of poly_shapes
    if geo_shape is not None and shapes_from_diff_with_min_area is not None:
        # fix rare cases where the generated polygons of the Voronoi regions don't fully cover `geo_shape`
        vor_polys_union = cascaded_union(poly_shapes)  # union of Voronoi regions
        diff = np.array(geo_shape.difference(vor_polys_union), dtype=object)  # "gaps"
        diff_areas = np.array([p.area for p in diff])  # areas of "gaps"
        # use only those "gaps" bigger than `shapes_from_diff_with_min_area` because very tiny areas are generated
        # at the borders due to floating point errors
        poly_shapes.extend(diff[diff_areas >= shapes_from_diff_with_min_area])

    return poly_shapes


def assign_points_to_voronoi_polygons(
    points, poly_shapes, accept_n_coord_duplicates=None, return_unassigned_points=False, coords=None
):
    """
    Assign a list/array of shapely Point objects `points` to their respective Voronoi polygons passed as list
    `poly_shapes`. Return a list of `assignments` of size `len(poly_shapes)` where ith element in `assignments`
    contains the index of the point in `points` that resides in the ith Voronoi region.
    Normally, 1-to-1 assignments are expected, i.e. for each Voronoi region in `poly_shapes` there's exactly one point
    in `points` belonging to this Voronoi region. However, if there are duplicate coordinates in `points`, then those
    duplicates will be assigned together to their Voronoi region and hence there is a 1-to-n relationship between
    Voronoi regions and points. If `accept_n_coord_duplicates` is set to None, then an an unspecified number of
    duplicates are allowed. If `accept_n_coord_duplicates` is 0, then no point duplicates are allowed, otherwise
    exactly `accept_n_coord_duplicates` duplicates are allowed.
    Set `return_unassigned_points` to additionally return a list of points that could not be assigned to any Voronoi
    region. `coords` can be passed in order to avoid another conversion from Point objects to NumPy coordinate array.
    """

    # do some checks first

    n_polys = len(poly_shapes)
    n_points = len(points)

    if n_polys > n_points:
        raise ValueError(
            "The number of voronoi regions must be smaller or equal to the number of points"
        )

    if accept_n_coord_duplicates is None:
        dupl_restricted = False
        accept_n_coord_duplicates = n_points - n_polys
    else:
        dupl_restricted = True

    expected_n_geocoords = n_points - accept_n_coord_duplicates

    if coords is None:
        coords = points_to_coords(points)
    elif len(coords) != n_points:
        raise ValueError("`coords` and `points` must have the same length")

    if accept_n_coord_duplicates >= 0 and n_polys != expected_n_geocoords:
        raise ValueError(
            "Unexpected number of geo-coordinates: %d (got %d polygons and expected %d geo-coordinates)"
            % (n_points, n_polys, expected_n_geocoords)
        )

    # get the Voronoi regions' centroids and calculate the distance between all centroid – input coordinate pairs
    poly_centroids = np.array([p.centroid.coords[0] for p in poly_shapes])
    poly_pt_dists = cdist(poly_centroids, coords)

    # generate the assignments
    assignments = []
    n_assigned_dupl = 0
    for i_poly, vor_poly in enumerate(poly_shapes):
        # indices to points sorted by distance to this Voronoi region's centroid
        closest_pt_indices = np.argsort(poly_pt_dists[i_poly])
        assigned_pts = []
        n_assigned = len(assigned_pts)
        for i_pt in closest_pt_indices:  # check each point with increasing distance
            pt = points[i_pt]

            if pt.intersects(
                vor_poly
            ):  # if this point is inside this Voronoi region, assign it to the region
                assigned_pts.append(i_pt)
                if n_assigned >= accept_n_coord_duplicates - n_assigned_dupl:
                    break

        if not assigned_pts:
            raise RuntimeError("Polygon %d does not contain any point" % i_poly)

        if accept_n_coord_duplicates == 0 and len(assigned_pts) > 1:
            raise RuntimeError(
                "No duplicate points allowed but polygon %d contains several points: %s"
                % (i_poly, str(assigned_pts))
            )

        # add the assignments for this Voronoi region
        assignments.append(assigned_pts)
        n_assigned_dupl += len(assigned_pts) - 1

    # make some final checks

    assert len(assignments) == len(poly_shapes)

    if dupl_restricted:
        assert n_assigned_dupl == accept_n_coord_duplicates
        assert sum(map(len, assignments)) == len(poly_shapes) + accept_n_coord_duplicates
        assert len(set(sum(assignments, []))) == n_points  # make sure all points were assigned
        unassigned_pt_indices = set()
    else:
        assigned_pt_indices = set(sum(assignments, []))
        unassigned_pt_indices = set(range(n_points)) - assigned_pt_indices

    if return_unassigned_points:
        return assignments, unassigned_pt_indices
    else:
        return assignments


def get_points_to_poly_assignments(poly_to_pt_assignments):
    """
    Reverse of poly to points assignments: Returns a list of size N, which is the number of points in
    `poly_to_pt_assignments`. Each list element is a index into the list of Voronoi regions.
    """
    pt_poly = [
        (i_pt, i_vor)
        for i_vor, pt_indices in enumerate(poly_to_pt_assignments)
        for i_pt in pt_indices
    ]

    return [i_vor for _, i_vor in sorted(pt_poly, key=lambda x: x[0])]
