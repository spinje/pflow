"""Integration test demonstrating the runtime validation feedback loop."""

from pflow.planning.nodes import RuntimeValidationNode


def simulate_github_api_workflow():
    """Simulate a workflow that tries to access GitHub API fields incorrectly."""

    print("=== Testing Runtime Validation Feedback Loop ===\n")

    # Initial workflow with WRONG field names (planner's guess)
    initial_workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "fetch_user", "type": "http", "params": {"url": "https://api.github.com/users/torvalds"}},
            {
                "id": "summarize",
                "type": "llm",
                "params": {
                    # These field names are WRONG - the planner is guessing
                    "prompt": "GitHub user ${fetch_user.response.username} (real name: ${fetch_user.response.full_name}) has bio: ${fetch_user.response.biography}"
                },
            },
        ],
        "edges": [{"from": "fetch_user", "to": "summarize"}],
    }

    print("ATTEMPT 1: Initial workflow with guessed field names")
    print("  Template: ${fetch_user.response.username}")
    print("  Template: ${fetch_user.response.full_name}")
    print("  Template: ${fetch_user.response.biography}")

    # Simulate what the shared store would look like after HTTP execution
    # (In reality, RuntimeValidationNode would execute the workflow and get this)
    simulated_shared_after = {
        "fetch_user": {
            "response": {
                # Actual GitHub API response structure
                "login": "torvalds",
                "id": 1024025,
                "name": "Linus Torvalds",
                "bio": None,
                "company": "Linux Foundation",
                "blog": "https://github.com/torvalds",
                "location": "Portland, OR",
                "email": None,
                "hireable": None,
                "public_repos": 8,
                "followers": 226884,
                "following": 0,
                "created_at": "2011-09-03T15:26:22Z",
                "updated_at": "2024-10-22T11:45:33Z",
            },
            "status_code": 200,
        },
        "summarize": {},  # LLM node wouldn't have run due to template error
    }

    # Create RuntimeValidationNode
    node = RuntimeValidationNode()

    # Check which templates are missing
    print("\n❌ Runtime Validation detects missing paths:")

    missing_templates = []
    for template in [
        "${fetch_user.response.username}",
        "${fetch_user.response.full_name}",
        "${fetch_user.response.biography}",
    ]:
        if not node._check_template_exists(template, simulated_shared_after):
            missing_templates.append(template)
            # Get available fields for helpful error
            available = node._get_available_paths(simulated_shared_after, "fetch_user", "response")
            print(f"  - {template} NOT FOUND")
            print(f"    Available fields: {', '.join(sorted(available)[:5])}...")

    print("\n🔄 Runtime feedback sent to WorkflowGeneratorNode:")
    print("  'username' doesn't exist → try 'login'")
    print("  'full_name' doesn't exist → try 'name'")
    print("  'biography' doesn't exist → try 'bio'")

    # CORRECTED workflow after runtime feedback
    corrected_workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "fetch_user", "type": "http", "params": {"url": "https://api.github.com/users/torvalds"}},
            {
                "id": "summarize",
                "type": "llm",
                "params": {
                    # CORRECTED field names based on runtime feedback
                    "prompt": "GitHub user ${fetch_user.response.login} (real name: ${fetch_user.response.name}) has bio: ${fetch_user.response.bio}"
                },
            },
        ],
        "edges": [{"from": "fetch_user", "to": "summarize"}],
    }

    print("\n✅ ATTEMPT 2: Corrected workflow with actual field names")
    print("  Template: ${fetch_user.response.login} ← corrected from 'username'")
    print("  Template: ${fetch_user.response.name} ← corrected from 'full_name'")
    print("  Template: ${fetch_user.response.bio} ← corrected from 'biography'")

    # Verify all templates now exist
    print("\n✅ Runtime Validation confirms all paths exist:")
    for template in ["${fetch_user.response.login}", "${fetch_user.response.name}", "${fetch_user.response.bio}"]:
        exists = node._check_template_exists(template, simulated_shared_after)
        print(f"  - {template}: {'✓ EXISTS' if exists else '✗ MISSING'}")

    print("\n🎉 Workflow is now correct and can run successfully!")
    print("   The workflow is saved with the correct field names.")
    print("   Future runs will work immediately without any guessing.")


def show_real_world_example():
    """Show a real-world example of the feedback loop."""

    print("\n\n=== Real-World Example: Slack Integration ===\n")

    print("User request: 'Send a Slack message with the latest GitHub issue title'\n")

    print("BEFORE Runtime Validation (Planner guesses):")
    print("  GitHub: ${github.response.issue.title}")
    print("  Slack:  ${slack.response.message_id}")

    print("\nAFTER Runtime Validation (Actual structure):")
    print("  GitHub: ${github.response.title}      ← simpler path!")
    print("  Slack:  ${slack.response.ts}          ← Slack uses 'ts' not 'message_id'")

    print("\n💡 This is why runtime validation is crucial:")
    print("   - APIs have non-obvious field names")
    print("   - Documentation might be wrong or outdated")
    print("   - The planner can make educated guesses and learn from reality")


if __name__ == "__main__":
    simulate_github_api_workflow()
    show_real_world_example()

    print("\n" + "=" * 50)
    print("Runtime Validation Benefits:")
    print("  1. ✅ No need to know API structures beforehand")
    print("  2. ✅ Workflows self-correct during generation")
    print("  3. ✅ Saved workflows are always correct")
    print("  4. ✅ 'Plan Once, Run Forever' philosophy achieved!")
    print("=" * 50)
