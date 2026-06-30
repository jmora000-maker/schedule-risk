
from pathlib import Path
from src.taxonomy import CorporateTaxonomyNormalizer
from src.inputs import ProjectArtifactLoader
from src.graph_manager import GraphManager
from src.rules import RuleEngine
from src.rag import RAGEngine

def debug_task_5():
    data_path = Path("data")
    normalizer = CorporateTaxonomyNormalizer()
    loader = ProjectArtifactLoader(normalizer)
    loader.load_project_artifacts(data_path)

    graph = GraphManager(graph_path="knowledge_graph/graph.json")
    graph.build_from_artifacts(
        loader.tasks,
        loader.milestones,
        loader.issues,
        loader.task_updates,
        loader.delivery_notes,
        loader.signals
    )
    graph.save()

    engine = RuleEngine(loader, graph)
    findings = engine.run()
    
    rag = RAGEngine(loader.raw_chunks)

    # --- DEBUGGING BLOCK START ---
    print("RAW CHUNK COUNTS BY ARTIFACT TYPE")
    counts = {}
    for ch in loader.raw_chunks:
        at = ch.artifact_type
        counts[at] = counts.get(at, 0) + 1
    print(counts)

    print("\nCHUNKS LINKED TO TASK UID 5")
    for ch in loader.raw_chunks:
        meta = ch.metadata or {}
        # ArtifactChunk has task_uid and task_id fields as attributes, not just metadata dict.
        # However, looking at the FileCode, the chunk is created via _make_chunk, which populates the object attributes.
        # The prompt says meta = ch.metadata or {}, but ArtifactChunk also has explicit attributes.
        # Let's check both.
        if str(getattr(ch, "task_uid", None)) == "5" or str(getattr(ch, "task_id", None)) == "5":
            print({
                "artifact_type": ch.artifact_type,
                "source_artifact": ch.source_artifact,
                "task_uid": getattr(ch, "task_uid", None),
                "task_id": getattr(ch, "task_id", None),
                "milestone_id": getattr(ch, "milestone_id", None),
                "text": ch.text[:200]
            })

    try:
        target = next(f for f in findings if str(f.task_uid) == "5")
        bundle = rag.build_evidence_bundle(target, graph)

        print("\nEVIDENCE FOR FINDING TASK UID 5")
        print("strength:", bundle.evidence_strength)
        print("sources:", bundle.source_types)
        for item in bundle.evidence_bundle:
            print({
                "artifact_type": item.artifact_type,
                "source_artifact": item.source_artifact,
                "text": item.text[:200]
            })
    except StopIteration:
        print("\nNo finding found for Task UID 5.")
    # --- DEBUGGING BLOCK END ---

if __name__ == "__main__":
    debug_task_5()
