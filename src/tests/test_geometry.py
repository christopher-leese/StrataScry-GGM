"""Coordinate, projection, and camera invariants needed by future map overlays."""
import math

import numpy as np
import pytest

from stratascry.geometry import GlobeCamera, globe_mesh_data, surface_point


@pytest.mark.parametrize("longitude,latitude,expected", [
    (0, 0, [1, 0, 0]), (90, 0, [0, 1, 0]),
    (-90, 0, [0, -1, 0]), (180, 0, [-1, 0, 0]),
    (40, 90, [0, 0, 1]), (40, -90, [0, 0, -1]),
])
def test_cardinal_coordinates(longitude, latitude, expected):
    np.testing.assert_allclose(surface_point(longitude, latitude), expected, atol=1e-14)


def test_sphere_seam_uv_orientation_and_outward_winding():
    points, faces, uv = globe_mesh_data(36, 18)
    np.testing.assert_allclose(np.linalg.norm(points, axis=1), 1)
    rows = points.reshape(19, 37, 3)
    coords = uv.reshape(19, 37, 2)
    np.testing.assert_allclose(rows[:, 0], rows[:, -1], atol=1e-14)
    np.testing.assert_allclose(coords[:, 0, 0], 0)
    np.testing.assert_allclose(coords[:, -1, 0], 1)
    np.testing.assert_allclose(rows[0, :, 2], -1)
    np.testing.assert_allclose(coords[0, :, 1], 0)
    np.testing.assert_allclose(rows[-1, :, 2], 1)
    np.testing.assert_allclose(coords[-1, :, 1], 1)
    np.testing.assert_allclose(rows[9, 18], [1, 0, 0], atol=1e-14)
    np.testing.assert_allclose(coords[9, 18], [.5, .5])
    quads = faces.reshape(-1, 5)[:, 1:]
    assert np.ptp(uv[quads, 0], axis=1).max() < .03
    # Exclude degenerate pole faces when checking their normals.
    a, b, c = points[quads[36:-36, 0]], points[quads[36:-36, 1]], points[quads[36:-36, 2]]
    assert np.all(np.einsum('ij,ij->i', np.cross(b-a, c-a), a) > 0)


def test_zoom_is_reversible_and_stays_outside_surface():
    nav = GlobeCamera()
    start = nav.distance
    nav.zoom(1)
    assert 1 < nav.distance < start
    nav.zoom(-1)
    assert nav.distance == pytest.approx(start)
    for _ in range(10):
        nav.zoom(10000)
    assert nav.distance == nav.MIN_DISTANCE > 1
    for _ in range(10):
        nav.zoom(-10000)
    assert nav.distance == nav.MAX_DISTANCE


def test_orbit_wraps_and_preserves_orthogonal_north_up_camera():
    nav = GlobeCamera(longitude=175, latitude=80)
    nav.orbit(east=20, north=20)
    assert (nav.longitude, nav.latitude) == (-165, 89.5)
    nav.orbit(east=-740, north=-190)
    assert -180 <= nav.longitude < 180
    assert nav.latitude == -89.5
    assert np.dot(nav.position, nav.view_up) == pytest.approx(0, abs=1e-14)
    assert np.linalg.norm(nav.view_up) == pytest.approx(1)
    assert nav.view_up[2] > 0


@pytest.mark.parametrize("aspect", [0.5, 1.0, 1.8, 3.0])
def test_reset_fits_globe_in_both_viewport_dimensions(aspect):
    nav = GlobeCamera(170, -80, 1.1)
    nav.reset(aspect)
    assert (nav.longitude, nav.latitude) == (-90, 25)
    globe_angle = math.asin(1 / nav.distance)
    vertical = math.radians(nav.VIEW_ANGLE / 2)
    horizontal = math.atan(math.tan(vertical) * aspect)
    assert globe_angle < min(vertical, horizontal)
