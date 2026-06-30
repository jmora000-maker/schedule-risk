from pathlib import Path
from src.inputs import ProjectArtifactLoader
from src.graph_manager import GraphManager
from src.rules import RuleEngine
from src.taxonomy import CorporateTaxonomyNormalizer

def test_rule_engine_integration():
    print("Testing RuleEngine integration...")
    # Setup
    data_path = Path("data")
    normalizer = CorporateTaxonomyNormalizer()
    loader = ProjectArtifactLoader(normalizer)
    loader.load_project_artifacts(data_path)
    
    # We might need to mock or ensure the graph manager doesn't try to write to a real file if not needed
    # But for an integration test, building the graph is fine.
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
    
    # Assertions on findings
    assert isinstance(findings, list)
    print(f"Found {len(findings)} risk findings.")
    
    # Validate normalization of severity
    for f in findings:
        # Check that severity is one of the normalized values
        assert f.severity in ["critical", "high", "medium", "low"], f"Invalid severity: {f.severity} in rule {f.rule_name}"
        
        # Check for evidence sources
        assert "evidence_sources" in f.metadata, f"Missing evidence_sources in {f.finding_id}"
        
        # Check confidence
        assert 0.0 <= f.confidence <= 1.0, f"Invalid confidence: {f.confidence} in rule {f.rule_name}"

    print("RuleEngine integration test passed.")

if __name__ == "__main__":
    test_rule_engine_integration()
