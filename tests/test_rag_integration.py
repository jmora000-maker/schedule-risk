from pathlib import Path
from src.inputs import ProjectArtifactLoader
from src.graph_manager import GraphManager
from src.rules import RuleEngine
from src.rag import RAGEngine
from src.taxonomy import CorporateTaxonomyNormalizer

def test_rag_engine_integration():
    print("Testing RAGEngine integration...")
    # Setup
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
    
    engine = RuleEngine(loader, graph)
    findings = engine.run()
    
    rag_engine = RAGEngine(loader.raw_chunks)
    
    for f in findings:
        bundle = rag_engine.build_evidence_bundle(f, graph)
        assert len(bundle.evidence_bundle) > 0
        
        # Verify deduplication: check if any two chunks have same text + source
        seen = set()
        for c in bundle.evidence_bundle:
            key = (c.text, c.source_artifact)
            assert key not in seen, f"Duplicate found: {key}"
            seen.add(key)
            
    print("RAGEngine integration test passed.")

if __name__ == "__main__":
    test_rag_engine_integration()
