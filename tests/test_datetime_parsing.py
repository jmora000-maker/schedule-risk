from src.inputs import ProjectArtifactLoader
from src.taxonomy import CorporateTaxonomyNormalizer
from pathlib import Path
import datetime

def test_datetime_parsing():
    print("Testing datetime parsing...")
    normalizer = CorporateTaxonomyNormalizer()
    loader = ProjectArtifactLoader(normalizer)
    tasks = loader.load_schedule_file(Path("data/compact_schedule.xml"))
    
    if len(tasks) > 0:
        task = tasks[0]
        print(f"Task: {task.name}")
        print(f"Start: {task.start} (type: {type(task.start)})")
        assert isinstance(task.start, datetime.datetime) or task.start is None
    else:
        print("No tasks loaded.")

if __name__ == "__main__":
    test_datetime_parsing()
