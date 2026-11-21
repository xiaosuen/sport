from dataclasses import dataclass
from .task_state import TaskState


@dataclass
class TaskContext:
    task_name: str = "situp"
    state: TaskState = TaskState.IDLE
    current_count: int = 0
    target_count: int = 20
    message: str = "system idle"

    def reset(self):
        self.task_name = "situp"
        self.state = TaskState.IDLE
        self.current_count = 0
        self.target_count = 20
        self.message = "system idle"