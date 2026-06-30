"""
Script Name: main.py
Description: Main entry point for the schedule-risk pipeline.
Author: James Mora
Created: 2026-06-28
Last Modified: 2026-06-28
"""


from pathlib import Path
from src.taxonomy import CorporateTaxonomyNormalizer
from src.inputs import ProjectArtifactLoader
from src.graph_manager import GraphManager
from src.rules import RuleEngine
from src.rag import RAGEngine
from src import llm, report

def run_automated_pipeline(data_path: Path = Path("data")) -> str:
    print("PIPELINE STARTED")

    # 1. Ingest Data
    print("STEP 1: Ingesting Data.")
    normalizer = CorporateTaxonomyNormalizer()
    loader = ProjectArtifactLoader(normalizer)
    loader.load_project_artifacts(data_path)

    # 2. Build Graph
    print("STEP 2: Building Knowledge Graph.")
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

    # 3. Rule Engine
    print("STEP 3: Running Rule Engine.")
    engine = RuleEngine(loader, graph)
    findings = engine.run()
    print(f" -> Found {len(findings)} risk findings.")

    # 4. RAG and LLM
    print("STEP 4: RAG & LLM Synthesis.")
    rag_engine = RAGEngine(loader.raw_chunks)
    explanations = {}
    evidence_map = {}
    print(f" -> Building evidence map for {len(findings)} findings.")
    print(" -> Sending findings to RAG Engine for evidence retrieval.")
    print(" -> Generating risk explanations using LLM.")
    print(" -> This may take a few minutes ...")
    
    for f in findings:
        bundle = rag_engine.build_evidence_bundle(f, graph)
        evidence_map[f.finding_id] = bundle

        exp = llm.generate_risk_explanation(f, bundle)
        exp.recommended_action = llm.clean_action_text(
            llm.recommend_next_action(f, bundle)
        )
        explanations[f.finding_id] = exp
    
    # 5. Reporting
    print("STEP 5: Generating Report.")
    report_text = report.build_schedule_risk_report(findings, explanations, evidence_map, loader.milestones)
    print("PIPELINE COMPLETED")
    
    return report_text

if __name__ == "__main__":
    run_automated_pipeline()

