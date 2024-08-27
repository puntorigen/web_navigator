# pydantic schemas
from pydantic import BaseModel, Field
from typing import List, Optional

class UserPrompt(BaseModel):
    prompt: str = Field(..., description="The user prompt containing a starting URL and a task to be performed.")

class ExtractedTask(BaseModel):
    url: str = Field(..., description="The extracted URL from the user prompt.")
    task: str = Field(..., description="The task to be performed on the URL.")
    what_do_you_plan_to_do: str = Field(..., description="What do you plan to achieve with the task to be performed?")

class HealingCommand(BaseModel):
    command: str = Field(..., description="The corrected Python Playwright command(s) to execute next. The command must be valid, handle coroutine results appropriately, and should avoid using complex constructs like async functions. If the task is complete, this can be an empty string.")
    task_completed: bool = Field(..., description="Indicates whether the task has been fully completed. Set to true if no further actions are needed.")
    reason_for_fix: str = Field(..., description="A rationale for why the new command will resolve the issue encountered, focusing on correcting any coroutine handling or other errors.")
    output: Optional[str] = Field(None, description="The direct result or answer extracted from the provided screenshots, if the task's answer is visually identified.")

class NextStepCommand(BaseModel):
    command: str = Field(..., description="The next valid Python Playwright command(s) to be executed. The command must handle coroutine results correctly and should be executable directly without complex constructs. If the task is complete, this can be an empty string.")
    task_completed: bool = Field(..., description="Indicates whether the task has been fully completed. Set to true if no further actions are needed.")
    what_do_you_plan_to_do: str = Field(..., description="An explanation of the intended result of the next step, guiding the execution of the Playwright command(s).")
    output: Optional[str] = Field(None, description="The direct result or answer extracted from the provided screenshots, if the task's answer is visually identified.")
