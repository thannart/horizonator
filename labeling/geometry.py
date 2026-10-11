'''The renderer's own geometry, reproduced exactly.

horizonator does NOT use geodesics: it works in the tangent plane at the
viewer, with an equirectangular mapping scaled by cos(viewer latitude) (see
horizonator_project() in horizonator-lib.c, and vertex.glsl). Labels must
use the very same mapping to land on the rendered peaks: a geodesic azimuth
would be off by a few tenths of a degree at 150 km, i.e. hundreds of pixels
in a high-resolution render'''

import math

# Same constant as horizonator-lib.c / vertex.glsl
R_EARTH_M = 6371000.0


def east_north_m(lat, lon, lat0, lon0):
    '''(east, north) in meters of (lat, lon) from (lat0, lon0), in the
    renderer's tangent plane'''
    east  = math.radians(lon - lon0) * R_EARTH_M * math.cos(math.radians(lat0))
    north = math.radians(lat - lat0) * R_EARTH_M
    return east, north


def azimuth_distance(lat, lon, lat0, lon0):
    '''Azimuth (degrees, 0 = north, 90 = east, in [0,360)) and horizontal
    distance (m) of (lat, lon) seen from (lat0, lon0)'''
    e, n = east_north_m(lat, lon, lat0, lon0)
    return math.degrees(math.atan2(e, n)) % 360.0, math.hypot(e, n)


def local_km(lon, lat, lat0):
    '''Equirectangular kilometers around latitude lat0: only used to measure
    areas and distances between nearby shapes (massif polygons), where a
    local planar approximation is plenty'''
    k = R_EARTH_M / 1000.0 * math.pi / 180.0
    return lon * k * math.cos(math.radians(lat0)), lat * k
