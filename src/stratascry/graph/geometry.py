# SPDX-License-Identifier: Apache-2.0
"""Spherical model distances and an invertible logical-pixel camera adapter."""
import math
import numpy as np

DISPLAY_RADIUS = 1.0001
EARTH_RADIUS_M = 6_371_008.8  # Declared spherical approximation, persisted in projects.
ANTIPODAL_EPS = 1e-7


def coordinate(lon, lat):
    if isinstance(lon, bool) or isinstance(lat, bool):
        raise ValueError('Coordinates must be numbers')
    lon, lat = float(lon), float(lat)
    if not math.isfinite(lon) or not math.isfinite(lat) or not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ValueError('Longitude must be −180…180° and latitude −90…90°')
    return ((lon + 180) % 360 - 180, lat)


def unit(coords):
    p = np.radians(np.asarray(coords, dtype=float).reshape(-1, 2))
    c = np.cos(p[:, 1])
    return np.column_stack((c * np.cos(p[:, 0]), c * np.sin(p[:, 0]), np.sin(p[:, 1])))


def geographic(v):
    v = np.asarray(v, dtype=float)
    v = v / np.linalg.norm(v)
    return coordinate(math.degrees(math.atan2(v[1], v[0])), math.degrees(math.asin(np.clip(v[2], -1, 1))))


def arc_angles(points):
    points = np.asarray(points)
    if len(points) < 2:
        return np.empty(0)
    return np.arctan2(np.linalg.norm(np.cross(points[:-1], points[1:]), axis=1),
                      np.einsum('ij,ij->i', points[:-1], points[1:]))


def length(coords, radius=EARTH_RADIUS_M):
    angles = arc_angles(unit(coords))
    if np.any(math.pi - angles < ANTIPODAL_EPS):
        raise ValueError('An antipodal segment needs an intermediate waypoint')
    value = float(angles.sum()) * radius
    if not math.isfinite(value):
        raise ValueError('Route length is not finite')
    return value


def tessellate(coords, step=math.radians(1), max_points=4096):
    """Short-arc control polyline; bounded derived geometry, never used for cost."""
    points = unit(coords)
    angles = arc_angles(points)
    if np.any(math.pi - angles < ANTIPODAL_EPS):
        raise ValueError('An antipodal segment needs an intermediate waypoint')
    counts = np.maximum(1, np.ceil(angles / step).astype(int))
    if counts.sum() + 1 > max_points:
        counts = np.maximum(1, np.floor(counts * (max_points-1) / counts.sum()).astype(int))
    result = []
    for a, b, theta, count in zip(points[:-1], points[1:], angles, counts):
        t = np.arange(count) / count
        if theta < 1e-12:
            result.append(np.repeat(a[None], count, axis=0))
        else:
            result.append((np.sin((1-t)*theta)[:, None]*a + np.sin(t*theta)[:, None]*b) / math.sin(theta))
    result.append(points[-1:])
    return np.concatenate(result)


def tessellate_many(routes, step=math.radians(1), max_points=4096):
    """Batch form of ``tessellate`` for many routes; returns one array per route.

    Produces the same points as calling ``tessellate`` on each route. Routes that
    hit ``max_points`` or contain an antipodal segment fall back to the scalar
    function (which raises for antipodal input).
    """
    if not routes:
        return []
    sizes = np.fromiter((len(r) for r in routes), dtype=int, count=len(routes))
    points = unit(np.concatenate([np.asarray(r, dtype=float).reshape(-1, 2) for r in routes]))
    ends = np.cumsum(sizes); starts = ends - sizes
    # Segments are consecutive point pairs that do not cross a route boundary.
    within = np.ones(len(points) - 1, dtype=bool)
    within[ends[:-1] - 1] = False
    a, b = points[:-1][within], points[1:][within]
    route_of_segment = np.repeat(np.arange(len(routes)), sizes - 1)
    theta = np.arctan2(np.linalg.norm(np.cross(a, b), axis=1), np.einsum('ij,ij->i', a, b))
    counts = np.maximum(1, np.ceil(theta / step).astype(int))
    per_route = np.bincount(route_of_segment, weights=counts, minlength=len(routes)).astype(int)
    antipodal = np.bincount(route_of_segment, weights=(math.pi - theta < ANTIPODAL_EPS), minlength=len(routes)) > 0
    scalar = (per_route + 1 > max_points) | antipodal
    keep = ~scalar[route_of_segment]
    a, b, theta, counts, seg_route = a[keep], b[keep], theta[keep], counts[keep], route_of_segment[keep]
    total = int(counts.sum())
    seg_of_point = np.repeat(np.arange(len(counts)), counts)
    first = np.cumsum(counts) - counts
    t = (np.arange(total) - first[seg_of_point]) / counts[seg_of_point]
    th = theta[seg_of_point]; pa, pb = a[seg_of_point], b[seg_of_point]
    safe = np.where(th < 1e-12, 1.0, np.sin(th))
    sampled = np.where((th < 1e-12)[:, None], pa,
                       (np.sin((1 - t) * th)[:, None] * pa + np.sin(t * th)[:, None] * pb) / safe[:, None])
    route_of_point = seg_route[seg_of_point]
    vector_routes = np.flatnonzero(~scalar)
    lengths = np.zeros(len(routes), dtype=int); lengths[vector_routes] = per_route[vector_routes] + 1
    out_end = np.cumsum(lengths); out_start = out_end - lengths
    out = np.empty((int(lengths.sum()), 3))
    # Each route's sampled points shift by the final points of earlier routes.
    shift = np.cumsum(~scalar) - 1
    out[np.arange(total) + shift[route_of_point]] = sampled
    out[out_end[vector_routes] - 1] = points[ends[vector_routes] - 1]
    result = []
    for i, route in enumerate(routes):
        result.append(tessellate(route, step, max_points) if scalar[i] else out[out_start[i]:out_end[i]])
    return result


class Projection:
    """Matches the north-up perspective camera using Qt logical pixels throughout."""
    def __init__(self, navigation, width, height):
        self.width, self.height = max(width, 1), max(height, 1)
        self.position = np.asarray(navigation.position)
        self.distance = navigation.distance
        self.front = self.position / self.distance
        self.up = np.asarray(navigation.view_up)
        self.right = np.cross(self.up, self.front)
        self.focal = self.height / (2 * math.tan(math.radians(navigation.VIEW_ANGLE/2)))
        self.horizon = DISPLAY_RADIUS / self.distance

    def project(self, points):
        p = np.asarray(points).reshape(-1, 3)
        depth = self.distance - DISPLAY_RADIUS * (p @ self.front)
        xy = np.column_stack((self.width/2 + self.focal*DISPLAY_RADIUS*(p @ self.right)/depth,
                              self.height/2 - self.focal*DISPLAY_RADIUS*(p @ self.up)/depth))
        return xy

    def visible(self, points):
        return np.asarray(points) @ self.front >= self.horizon - 1e-12

    def pick(self, x, y):
        d = -self.front + (x-self.width/2)/self.focal*self.right - (y-self.height/2)/self.focal*self.up
        d /= np.linalg.norm(d)
        b = float(self.position @ d)
        disc = b*b - (self.distance*self.distance - DISPLAY_RADIUS**2)
        if disc <= 1e-15:
            return None
        t = -b - math.sqrt(disc)
        return geographic(self.position+t*d) if t > 0 else None

    def clipped_segments(self, points):
        """Clip sampled spherical segments to the horizon, including near-tangent arcs.

        Solve intersections in each arc's own orthonormal plane, avoiding depth
        buffer differences between imagery and the overlay.
        """
        return self.clipped_pairs(points[:-1], points[1:])[0]

    def clipped_pairs(self, a, b):
        indices = np.arange(len(a))
        dot = np.clip(np.einsum('ij,ij->i', a, b), -1, 1)
        theta = np.arctan2(np.linalg.norm(np.cross(a, b), axis=1), dot)
        valid = theta > 1e-13
        indices = indices[valid]
        a, b, theta, dot = a[valid], b[valid], theta[valid], dot[valid]
        if not len(a):
            return np.empty((0, 2, 2)), np.empty(0,dtype=int)
        tangent = (b-dot[:, None]*a)/np.sin(theta)[:, None]
        u, v = a @ self.front, tangent @ self.front
        amplitude = np.hypot(u, v)
        potential = amplitude >= self.horizon
        indices = indices[potential]
        a, tangent, theta, u, v, amplitude = (x[potential] for x in (a,tangent,theta,u,v,amplitude))
        if not len(a):
            return np.empty((0, 2, 2)), np.empty(0,dtype=int)
        center = np.arctan2(v, u)
        half = np.arccos(np.clip(self.horizon/amplitude, -1, 1))
        # Short tessellated arcs are < pi; the closest lobe can cross angle zero.
        low, high = np.maximum(0, center-half), np.minimum(theta, center+half)
        ok = high >= low
        indices = indices[ok]
        a, tangent, low, high = a[ok], tangent[ok], low[ok], high[ok]
        p = np.cos(low)[:,None]*a + np.sin(low)[:,None]*tangent
        q = np.cos(high)[:,None]*a + np.sin(high)[:,None]*tangent
        return np.stack((self.project(p), self.project(q)), axis=1), indices
