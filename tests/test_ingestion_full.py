from src.inputs import ProjectArtifactLoader
from src.taxonomy import CorporateTaxonomyNormalizer
from pathlib import Path

def test_happy_path():
    print("Testing happy path...")
    normalizer = CorporateTaxonomyNormalizer()
    loader = ProjectArtifactLoader(normalizer)
    tasks = loader.load_schedule_file(Path("data/compact_schedule.xml"))
    assert len(tasks) > 0
    print(f"Loaded {len(tasks)} tasks.")
    # Check one task to ensure it's loaded correctly
    task = tasks[0]
    print(f"Task 0: {task.name}, UID: {task.task_uid}")

if __name__ == "__main__":
    test_happy_path()
