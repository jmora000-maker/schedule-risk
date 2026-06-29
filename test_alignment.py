
from src.taxonomy import CorporateTaxonomyNormalizer
from src.inputs import ProjectArtifactLoader
from src.graph_manager import GraphManager
from src.rules import RuleEngine
from src.rag import RAGEngine
from src import llm, report
from pathlib import Path

def test_pipeline():
    schedule_path = Path("data/compact_schedule.xml")
    notes_path = Path("data/meeting_notes_v3.docx")
    
    print(f"Loading data from {schedule_path} and {notes_path}")
    
    # Initialize Loader
    normalizer = CorporateTaxonomyNormalizer()
    loader = ProjectArtifactLoader(normalizer)
    loader.load_project_artifacts(Path("data"))
    
    print("Data ingested. Building Graph...")
    
    # Initialize GraphManager and build graph
    graph = GraphManager(graph_path="knowledge_graph/graph_test.json")
    graph.build_from_artifacts(
        loader.tasks,
        loader.milestones,
        loader.issues,
        loader.task_updates,
        loader.delivery_notes,
        loader.signals
    )
    graph.save()
    print(f"Graph saved to {graph.graph_path}")
    
    print("Running RuleEngine...")
    engine = RuleEngine(loader, graph)
    findings = engine.run()
    
    print(f"Found {len(findings)} risk findings.")
    for f in findings:
        print(f" - {f.rule_name}: {f.summary} (Severity: {f.severity})")

    print("\nTesting RAGEngine, LLM, and Report Generation...")
    rag_engine = RAGEngine(loader.raw_chunks)
    
    explanations = {}
    evidence_map = {}
    
    for f in findings:
        bundle = rag_engine.build_evidence_bundle(f, graph)
        evidence_map[f.finding_id] = bundle
        explanations[f.finding_id] = llm.generate_risk_explanation(f, bundle)
        
    print(f"Generated {len(explanations)} explanations and {len(evidence_map)} evidence bundles.")
    
    report_text = report.build_schedule_risk_report(findings, explanations, evidence_map)
    print(f"Report generated and saved.")

if __name__ == "__main__":
    try:
        test_pipeline()
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
