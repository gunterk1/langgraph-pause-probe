"""E2 -- Does one paused branch cancel its siblings?

discogs-filler, ADK 2.0:

    As soon as one branch pauses, ADK cancels all the others -- including the
    ones that were about to create a listing. With nineteen records, one is
    always paused, so nothing ever got through.

Same setup here: nineteen records, eighteen of them already graded and needing
nothing but a listing, one still open and therefore pausing for a human. The
question is simply how many of the eighteen reach the listing node while that
one branch waits.

The answer is read off the world, not off a log: a listing either happened or
it did not.
"""

from __future__ import annotations

import pathlib
import tempfile

from langgraph.checkpoint.sqlite import SqliteSaver

from probe import graph as G
from probe.world import World

ITEMS = [f"r{i:02d}" for i in range(19)]
NEEDS_HUMAN = "r07"


def run(tmp: pathlib.Path) -> dict:
    world = World(tmp / "world.db")
    world.seed(ITEMS)
    for item in ITEMS:
        if item != NEEDS_HUMAN:
            world.mark_graded(item)

    with SqliteSaver.from_conn_string(str(tmp / "cp.db")) as cp:
        app = G.build(world, cp)
        cfg = {"configurable": {"thread_id": "e2"}}
        out = app.invoke({"items": ITEMS}, cfg)

        expected = [i for i in ITEMS if i != NEEDS_HUMAN]
        listed = world.listed()
        return {
            "records": len(ITEMS),
            "paused": sorted(i.value["item_id"] for i in out.get("__interrupt__", [])),
            "siblings_expected": len(expected),
            "siblings_listed": len(listed),
            "missing": sorted(set(expected) - set(listed)),
        }


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        for k, v in run(pathlib.Path(d)).items():
            print(f"{k:20} {v}")
