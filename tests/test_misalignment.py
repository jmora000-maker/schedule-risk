from src.models import ScheduleTask

def test_misalignment():
    print("Testing correct instantiation...")
    try:
        # Should succeed now
        ScheduleTask(task_uid=1, task_id=1, name="test")
        print("Success: Instantiation succeeded")
    except Exception as e:
        print(f"Error: Instantiation failed unexpectedly: {e}")

if __name__ == "__main__":
    test_misalignment()
