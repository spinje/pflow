The Real Problem

  It's not just about name resolution - the system lacks a central workflow management authority:

  1. No Save Functionality - Critical gap for "Plan Once, Run Forever"
  2. Scattered Loading - 4 different implementations across components
  3. No Name Resolution - Each component uses file paths directly
  4. No Lifecycle Management - Can't list, update, or delete workflows

  The Solution: WorkflowManager

  A centralized service that owns the workflow lifecycle:

  class WorkflowManager:
      """Single source of truth for workflow operations"""

      def save(self, name: str, workflow_ir: dict) -> str:
          """Save workflow after user approval"""
          path = f"~/.pflow/workflows/{name}.json"
          # Validate, add metadata, write to disk

      def load(self, name: str) -> dict:
          """Load workflow by name for execution"""

      def get_path(self, name: str) -> str:
          """Resolve name to path for WorkflowExecutor"""

      def list_all(self) -> List[WorkflowMetadata]:
          """List workflows for discovery/context builder"""

  This would:
  - Implement missing save (currently workflows can't be saved!)
  - Enable name-based references (planner can use workflow names)
  - Consolidate scattered logic (one place for all workflow operations)
  - Provide growth path (versioning, search, etc.)
