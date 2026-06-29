from pathlib import Path
from src.inputs import ProjectArtifactLoader
from src.taxonomy import CorporateTaxonomyNormalizer

def test_xml():
    path = Path("data/compact_schedule.xml")
    if not path.exists():
        print("File not found")
        return
    
    normalizer = CorporateTaxonomyNormalizer()
    loader = ProjectArtifactLoader(normalizer)
    
    try:
        tasks = loader.load_schedule_file(path)
        print(f"Successfully loaded {len(tasks)} tasks from {path}")
        if tasks:
            print(f"Sample task: {tasks[0].name}, UID: {tasks[0].task_uid}")
            # Ensure assignments are present and type is correct
            if tasks[0].assignments:
                print(f"Sample task has {len(tasks[0].assignments)} assignments.")
    except Exception as e:
        print(f"Error loading {path}: {e}")

if __name__ == "__main__":
    test_xml()
