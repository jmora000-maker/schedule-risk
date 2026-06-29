from src.models import ScheduleTask

def test_extra_field():
    print("Testing extra field...")
    try:
        # Instantiating with an unknown field
        ScheduleTask(name="Bad Task", unknown_field="This should fail")
        print("Error: Should have failed")
    except Exception as e:
        print(f"Caught expected error: {e}")

if __name__ == "__main__":
    test_extra_field()
