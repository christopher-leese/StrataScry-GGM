import hashlib
from importlib.resources import files
import json

from PIL import Image


def test_bundled_image_matches_recorded_nasa_derivative():
    assets = files("stratascry").joinpath("assets")
    provenance = json.loads(assets.joinpath("blue-marble.json").read_text())
    asset = assets.joinpath(provenance["file"])
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == provenance["sha256"]
    with Image.open(str(asset)) as image:
        assert image.size == (provenance["width"], provenance["height"]) == (5400, 2700)
    assert "Reto Stöckli" in assets.joinpath("ATTRIBUTION.md").read_text()
