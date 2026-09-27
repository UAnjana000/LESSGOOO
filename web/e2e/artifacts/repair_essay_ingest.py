"""Resume ingest on the essay after pages were attached. Throwaway e2e data only."""
import random

from archive.ingest import graph as ingest_graph
from archive.worker import postgres_checkpointer

SEED = "e2e-repair"
with postgres_checkpointer() as cp:
    g = ingest_graph.build_ingest_graph(checkpointer=cp, rng=random.Random(7))
    print({"has_checkpoint": ingest_graph.has_checkpoint(g, 1)})
    state = ingest_graph.resume_reprocess(g, 1, SEED)
    print({
        "outcomes": state.get("page_outcomes"),
        "problems": state.get("review_problems"),
        "error": state.get("error"),
        "next": "interrupted" if "__interrupt__" in state else "done",
    })
