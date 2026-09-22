# Copyright 2026 Christopher Leese
# SPDX-License-Identifier: Apache-2.0
"""Globe coordinates and camera state, independent of Qt and the renderer.

Right-handed coordinates: +X = 0° longitude on the equator, +Y = 90°E,
+Z = north. Longitude increases eastwards, latitude northwards. Radius = 1.
"""
from dataclasses import dataclass
import math

import numpy as np


def globe_mesh_data(longitude_steps: int = 360, latitude_steps: int = 180):
    """Return points, quad faces, and UVs for an equirectangular texture.

    Duplicate the antimeridian vertices so triangles never interpolate across
    the texture seam. VTK texture V=0 is the bottom (south) of the image.
    """
    if longitude_steps < 3 or latitude_steps < 2:
        raise ValueError("A sphere needs at least 3 longitude and 2 latitude steps")
    lon = np.linspace(-np.pi, np.pi, longitude_steps + 1)
    lat = np.linspace(-np.pi / 2, np.pi / 2, latitude_steps + 1)
    longitude, latitude = np.meshgrid(lon, lat)
    points = np.column_stack((
        (np.cos(latitude) * np.cos(longitude)).ravel(),
        (np.cos(latitude) * np.sin(longitude)).ravel(),
        np.sin(latitude).ravel(),
    ))
    uv = np.column_stack((
        ((longitude + np.pi) / (2 * np.pi)).ravel(),
        ((latitude + np.pi / 2) / np.pi).ravel(),
    ))
    rows, cols = np.meshgrid(np.arange(latitude_steps),
                            np.arange(longitude_steps), indexing="ij")
    first = (rows * (longitude_steps + 1) + cols).ravel()
    faces = np.column_stack((np.full(first.size, 4), first, first + 1,
                             first + longitude_steps + 2,
                             first + longitude_steps + 1)).ravel()
    return points, faces, uv


def surface_point(longitude: float, latitude: float, radius: float = 1.0):
    lon, lat = math.radians(longitude), math.radians(latitude)
    return np.array((radius * math.cos(lat) * math.cos(lon),
                     radius * math.cos(lat) * math.sin(lon),
                     radius * math.sin(lat)))


@dataclass
class GlobeCamera:
    longitude: float = -90.0
    latitude: float = 25.0
    distance: float = 3.6

    MIN_DISTANCE = 1.0002
    MAX_DISTANCE = 20.0
    VIEW_ANGLE = 38.0

    def orbit(self, east: float = 0, north: float = 0):
        self.longitude = (self.longitude + east + 180) % 360 - 180
        # Avoid an undefined north-up direction at the exact poles.
        self.latitude = max(-89.5, min(89.5, self.latitude + north))

    def zoom(self, steps: float):
        # Positive steps move closer. Clamp before exponentiation as well.
        steps = max(-100, min(100, steps))
        self.distance = max(self.MIN_DISTANCE, min(
            self.MAX_DISTANCE, 1 + (self.distance - 1) * math.exp(-0.16 * steps)))

    def reset(self, aspect: float = 1.5):
        self.longitude, self.latitude = -90.0, 25.0
        vertical = math.radians(self.VIEW_ANGLE / 2)
        horizontal = math.atan(math.tan(vertical) * max(0.1, aspect))
        self.distance = min(self.MAX_DISTANCE,
                            1.12 / math.sin(min(vertical, horizontal)))

    @property
    def position(self):
        return surface_point(self.longitude, self.latitude, self.distance)

    @property
    def view_up(self):
        # Local north, perpendicular to the camera's radial direction.
        lon, lat = math.radians(self.longitude), math.radians(self.latitude)
        return (-math.sin(lat) * math.cos(lon),
                -math.sin(lat) * math.sin(lon), math.cos(lat))
