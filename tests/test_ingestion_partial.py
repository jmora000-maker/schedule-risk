from src.inputs import ProjectArtifactLoader
from src.taxonomy import CorporateTaxonomyNormalizer
from pathlib import Path
import xml.etree.ElementTree as ET

def test_partial_fields():
    print("Testing partial fields...")
    # Create a minimal XML with only essential fields
    xml_content = """<Project xmlns="http://schemas.microsoft.com/project">
        <Tasks>
            <Task>
                <UID>1</UID>
                <Name>Partial Task</Name>
            </Task>
        </Tasks>
    </Project>"""
    with open("data/partial_schedule.xml", "w") as f:
        f.write(xml_content)

    normalizer = CorporateTaxonomyNormalizer()
    loader = ProjectArtifactLoader(normalizer)
    tasks = loader.load_schedule_file(Path("data/partial_schedule.xml"))
    assert len(tasks) == 1
    print(f"Loaded {len(tasks)} tasks: {tasks[0].name}, UID: {tasks[0].task_uid}")

if __name__ == "__main__":
    test_partial_fields()
