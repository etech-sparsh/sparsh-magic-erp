from pydantic import BaseModel


# Task Categories / Tags (collections: "task_categories", "task_tags"). Previously these
# were only ever derived on the fly from whatever tasks a given list view happened to have
# loaded (see git history of TaskListView.jsx) — a value typed while creating a task only
# "existed" for as long as a task using it was visible in that same scoped/filtered list.
# These are now first-class, persisted, and shared across every task list/create flow.
class NameCreate(BaseModel):
    name: str
