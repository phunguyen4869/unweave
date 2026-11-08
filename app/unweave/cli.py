"""CLI: JSON results on stdout, diagnostics on stderr."""

import argparse
import json
import sys
from pathlib import Path

from .audio.pipeline import DEFAULT_MODEL, LEAF_STEMS, STEM_CHOICES, separate, train
from .audio.exports import FORMATS

# `--stems`/`--group` also accept the guitar-split leaves, which the separation
# model never produces; argparse choices must therefore include them or a plan
# that splits the guitar is rejected before the pipeline ever sees it.
PLAN_CHOICES = (*STEM_CHOICES, *LEAF_STEMS)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="unweave", description="Separate audio into WAV stems.")
    commands = root.add_subparsers(dest="command", required=True)
    split = commands.add_parser("separate", help="Separate a local file or explicit YouTube video")
    source = split.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--youtube", help="HTTPS video URL for audio you may download/process")
    split.add_argument("--output", "--output-folder", type=Path,
                       help="Destination folder (created if needed). Default: input folder/filename without extension; YouTube: stems/track-<id>.")
    split.add_argument("--model", help=f"Override automatic model selection (default: {DEFAULT_MODEL})")
    split.add_argument("--stems", nargs="*", choices=PLAN_CHOICES,
                       help="Stems that get their own file (lead/rhythm need --split-guitar). Pass it empty for a plan with no own files.")
    split.add_argument("--group", nargs="+", choices=PLAN_CHOICES,
                       help="Stems folded into other.flac; they are mixed in and not written on their own.")
    split.add_argument("--split-guitar", action="store_true",
                       help="Split the guitar stem into lead and rhythm after separation.")
    split.add_argument("--start", type=float, help="Start of the section in seconds (requires --end)")
    split.add_argument("--end", type=float, help="End of the section in seconds (requires --start)")
    split.add_argument("--cache", type=Path, default=Path(".sound-razor/models"))
    guitar = commands.add_parser("split-guitar", help="Split an existing guitar stem into lead and rhythm")
    guitar.add_argument("--file", type=Path, required=True)
    guitar.add_argument("--output", type=Path, required=True)
    guitar.add_argument("--start", type=float, help="Start of the section in seconds (requires --end)")
    guitar.add_argument("--end", type=float, help="End of the section in seconds (requires --start)")
    guitar.add_argument("--cache", type=Path, default=Path(".sound-razor/models"))
    guitar.add_argument("--replace-source", action="store_true",
                        help="Remove the guitar stem after a whole split, or mute the split section in it (it must be in --output)")
    export = commands.add_parser("export", help="Copy project stems into other formats")
    export.add_argument("--project", type=Path, required=True)
    export.add_argument("--formats", nargs="+", choices=tuple(FORMATS), default=["flac"])
    export.add_argument("--stems", nargs="+", help="Stem filenames; default all current stems")
    export.add_argument("--no-prevent-clipping", action="store_true")
    training = commands.add_parser("train", help="Fine-tuning boundary (not implemented)")
    training.add_argument("dataset", type=Path)
    ui = commands.add_parser("ui", help="Open a local project library and stem player in your browser")
    ui.add_argument("--projects", type=Path, help="Projects folder; otherwise use the last selection or choose in the UI")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--cache", type=Path, default=Path(".sound-razor/models"))
    return root


def main(argv: list[str] | None = None) -> int:
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    if args.command in {"separate", "split-guitar"} and (args.start is None) != (args.end is None):
        argument_parser.error("--start and --end must be used together.")
    try:
        trim = (args.start, args.end) if getattr(args, "start", None) is not None else None
        if args.command == "split-guitar":
            from .audio.guitar_split import split_guitar
            result = [str(path) for path in split_guitar(args.file, args.output, args.cache, trim, args.replace_source)]
        elif args.command == "export":
            from .audio.exports import export_stems
            from .projects import describe_project
            project = args.project.expanduser().resolve()
            info = describe_project(project)
            stems = args.stems or [item["file"] for item in info["stems"]]

            last = [None]

            def report(completed, total, label):
                if label != last[0]:
                    last[0] = label
                    print(label, file=sys.stderr, flush=True)

            result = [str(path) for path in export_stems(
                project, stems, args.formats, not args.no_prevent_clipping, report,
            )]
        elif args.command == "train":
            train(args.dataset)
            return 0
        elif args.command == "ui":
            from .webui import serve
            serve(args.projects, args.port, args.cache)
            return 0
        else:
            result = [str(path) for path in separate(
                str(args.file) if args.file else args.youtube,
                args.output, args.model, args.cache, youtube=bool(args.youtube), stems=args.stems,
                group=args.group, split_guitar=args.split_guitar, trim=trim,
            )]
        print(json.dumps(result, indent=2))
        return 0
    except KeyboardInterrupt:
        print("unweave: interrupted", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"unweave: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
