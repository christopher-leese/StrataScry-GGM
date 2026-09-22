"""Command-line preparation for reproducible, offline map packages."""
import argparse
import json
import sys

from .model import load_package
from .prepare import PrepareOptions, build_package
from .sources import inspect_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Inspect local elevation sources")
    build = commands.add_parser("prepare", help="Create a new local package directory")
    for command in (inspect, build):
        command.add_argument("--source", choices=("nasadem", "usgs"), required=True)
        command.add_argument("files", nargs="+")
    build.add_argument("--name", required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--bounds", type=float, nargs=4, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    build.add_argument("--max-side", type=int, default=2048)
    build.add_argument("--units", choices=("from_metadata", "metres", "feet", "us_survey_feet"), default="from_metadata")
    build.add_argument("--vertical-reference", default="")
    build.add_argument("--source-url", default="")
    build.add_argument("--acquisition-date", default="")
    validate = commands.add_parser("validate", help="Validate a prepared package, including checksums")
    validate.add_argument("directory")
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            report = inspect_sources(args.files, args.source)
            # Avoid dumping long source WKT/XML when simply inspecting a file.
            for source in report["sources"]:
                source.pop("crs_wkt", None)
                source.get("sidecar_metadata", {}).pop("xml", None)
            print(json.dumps(report, indent=2))
        elif args.command == "prepare":
            options = PrepareOptions(args.files, args.source, args.output, args.name,
                args.bounds, args.max_side, args.units, args.vertical_reference,
                args.source_url, args.acquisition_date)
            path = build_package(options, progress=lambda n, text: print(f"{n}% {text}", file=sys.stderr))
            print(path)
        else:
            package = load_package(args.directory)
            print(f"Valid: {package.name} ({package.rgba.shape[1]} × {package.rgba.shape[0]})")
    except Exception as error:
        parser.exit(1, f"Map package error: {error}\n")


if __name__ == "__main__":
    main()
