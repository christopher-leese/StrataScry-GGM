# SPDX-License-Identifier: Apache-2.0
"""VTK map actors. Construct/update only on the GUI thread."""
import math

import numpy as np
import pyvista as pv

from ..geometry import surface_point

PATCH_RADIUS = 1.000002
BORDER_RADIUS = 1.000006


def patch_mesh(bounds):
    w, s, e, n = bounds
    columns = max(16, min(512, math.ceil((e-w) / .03)))
    rows = max(16, min(512, math.ceil((n-s) / .03)))
    longitude, latitude = np.meshgrid(np.linspace(w, e, columns+1), np.linspace(s, n, rows+1))
    lon, lat = np.radians(longitude), np.radians(latitude)
    points = PATCH_RADIUS * np.column_stack(((np.cos(lat)*np.cos(lon)).ravel(),
                  (np.cos(lat)*np.sin(lon)).ravel(), np.sin(lat).ravel()))
    first = (np.arange(rows)[:, None]*(columns+1) + np.arange(columns)).ravel()
    faces = np.column_stack((np.full(first.size,4), first, first+1,
                             first+columns+2, first+columns+1)).ravel()
    mesh = pv.PolyData(points, faces)
    mesh.active_texture_coordinates = np.column_stack((((longitude-w)/(e-w)).ravel(),
                                                        ((latitude-s)/(n-s)).ravel()))
    return mesh


def border_mesh(rings, broken=False):
    points, cells = [], []
    for ring in rings:
        for a, b in zip(ring, ring[1:]):
            count = max(1, math.ceil(max(abs(b[0]-a[0]), abs(b[1]-a[1]))/.025))
            segment = np.linspace(a, b, count+1)
            for j, (left, right) in enumerate(zip(segment, segment[1:])):
                if broken and j % 4 == 3:
                    continue
                offset = len(points)
                points.extend((surface_point(*left, BORDER_RADIUS), surface_point(*right, BORDER_RADIUS)))
                cells.extend((2, offset, offset+1))
    if not points:
        return None
    mesh = pv.PolyData(np.array(points))
    mesh.verts = np.empty(0, dtype=int)
    mesh.lines = np.array(cells)
    return mesh


class PackageRenderer:
    def __init__(self, globe):
        self.globe = globe
        self.package = None
        self.actor = None
        self.borders = []
        self.coverage_visible = True
        self.opacity = 1.0
        self.brightness = 1.0

    def set_package(self, package):
        if self.actor is not None:
            self.globe.remove_actor(self.actor, reset_camera=False, render=False)
            self.actor = None
        self.package = package
        if package is not None:
            texture = pv.numpy_to_texture(package.rgba)
            texture.interpolate = True
            texture.repeat = False
            self.actor = self.globe.add_mesh(patch_mesh(package.bounds), texture=texture,
                lighting=False, name="regional-map", pickable=False, reset_camera=False, render=False)
            self.apply_appearance()
        self.globe.render()

    def set_coverage(self, entries):
        for actor in self.borders:
            self.globe.remove_actor(actor, reset_camera=False, render=False)
        self.borders = []
        for entry in entries:
            active = self.package is not None and entry["id"] == self.package.id
            if active:
                rings = [ring for feature in self.package.coverage["features"]
                         for ring in feature["geometry"]["coordinates"]]
            else:
                w, s, e, n = entry["bounds"]
                rings = [[[w,s],[e,s],[e,n],[w,n],[w,s]]]
            mesh = border_mesh(rings, broken=not active)
            if mesh is not None:
                actor = self.globe.add_mesh(mesh, color="#73d4d1" if active else "#8395a9",
                    line_width=2 if active else 1, lighting=False, pickable=False,
                    reset_camera=False, render=False)
                actor.SetVisibility(self.coverage_visible)
                self.borders.append(actor)
        self.globe.render()

    def set_coverage_visible(self, visible):
        self.coverage_visible = visible
        for actor in self.borders:
            actor.SetVisibility(visible)
        self.globe.render()

    def apply_appearance(self):
        for actor in (self.globe.earth_actor, self.actor):
            if actor is not None:
                actor.GetProperty().SetColor(self.brightness, self.brightness, self.brightness)
        if self.actor is not None:
            self.actor.GetProperty().SetOpacity(self.opacity)
        self.globe.render()

    def zoom_to_package(self):
        if self.package is None:
            return
        w, s, e, n = self.package.bounds
        nav = self.globe.navigation
        nav.longitude, nav.latitude = (w+e)/2, (s+n)/2
        normal = surface_point(nav.longitude, nav.latitude)
        up = np.array(nav.view_up)
        right = np.cross(up, normal)
        vertical = math.tan(math.radians(nav.VIEW_ANGLE/2))
        horizontal = vertical * max(1,self.globe.width()) / max(1,self.globe.height())
        candidates = []
        for longitude in np.linspace(w,e,9):
            for latitude in np.linspace(s,n,9):
                point = surface_point(longitude,latitude,PATCH_RADIUS)
                candidates.append(np.dot(point,normal) + max(abs(np.dot(point,right))/horizontal,
                                                           abs(np.dot(point,up))/vertical))
        nav.distance = max(nav.MIN_DISTANCE, min(nav.MAX_DISTANCE, 1+(max(candidates)-1)*1.15))
        self.globe.apply_camera()
