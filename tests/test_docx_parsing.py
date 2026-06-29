from pathlib import Path
from src.inputs import ProjectArtifactLoader
from src.taxonomy import CorporateTaxonomyNormalizer

def test_docx():
    path = Path("data/meeting_notes_v3.docx")
    if not path.exists():
        print("File not found")
        return
    
    normalizer = CorporateTaxonomyNormalizer()
    loader = ProjectArtifactLoader(normalizer)
    
    try:
        loader.load_meeting_notes(path)
        print(f"Successfully loaded {len(loader.signals)} signals from {path}")
        for s in loader.signals:
            print(f" - {s.signal_type} at task {s.task_id}")
    except Exception as e:
        print(f"Error loading {path}: {e}")

if __name__ == "__main__":
    test_docx()
