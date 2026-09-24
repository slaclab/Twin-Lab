"""Pick a reviewed model and open its viewer.

Any arguments this launcher does not recognise are passed on to the viewer it starts.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

from .paths import REPOSITORY_ROOT


@dataclass(frozen=True)
class Model:
    key: str
    title: str
    collision: tuple[str, ...]
    motion: tuple[str, ...]


INVENTORY_43841 = str(
    REPOSITORY_ROOT / "cad" / "DSG-000040389" / "reviews" / "43841-stage-stack.inventory.yaml"
)
BUILD_95835 = str(REPOSITORY_ROOT / "cad" / "DSG-000095835" / "build.py")

MODELS = (
    Model(
        "43841",
        "DSG-000040389 *43841 polycapillary stage stack (22 joints)",
        ("-m", "twin_lab.collision_viewer", INVENTORY_43841),
        ("-m", "twin_lab.stage_cad_viewer", INVENTORY_43841),
    ),
    Model(
        "95835",
        "DSG-000095835 offline assembly (12 joints)",
        (BUILD_95835, "--view"),
        (BUILD_95835, "--collision", "none", "--view"),
    ),
)


def print_models() -> None:
    for index, model in enumerate(MODELS, 1):
        print(f"  {index}) {model.key}  {model.title}")


def choose_model() -> Model:
    print("Twin Lab models:")
    print_models()
    while True:
        try:
            answer = input(f"Select a model [1-{len(MODELS)}, default 1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise SystemExit(130) from None
        if not answer:
            return MODELS[0]
        for index, model in enumerate(MODELS, 1):
            if answer in (str(index), model.key):
                return model
        print(f"Unknown choice {answer!r}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "model", nargs="?", choices=[model.key for model in MODELS],
        help="Model to open; prompts for one when omitted",
    )
    parser.add_argument(
        "--motion-only", action="store_true",
        help="Open the lighter viewer without collision checking",
    )
    parser.add_argument("--list", action="store_true", help="List the models and exit")
    args, passthrough = parser.parse_known_args()

    if args.list:
        print_models()
        return
    if args.model is None:
        if not sys.stdin.isatty():
            parser.error("no model given and no terminal to prompt on")
        model = choose_model()
    else:
        model = next(model for model in MODELS if model.key == args.model)

    command = [sys.executable, *(model.motion if args.motion_only else model.collision)]
    command += passthrough
    print("Running:", " ".join(command), flush=True)
    # Replace this process so Ctrl-C reaches the viewer directly and caches close cleanly.
    os.execv(sys.executable, command)


if __name__ == "__main__":
    main()
