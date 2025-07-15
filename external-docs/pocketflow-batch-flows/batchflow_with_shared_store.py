#!/usr/bin/env python3
"""
BatchFlow Example with Shared Store Considerations

This example shows important patterns when using BatchFlow:
1. How shared store behaves across batch iterations
2. How to accumulate results across runs
3. Parameter passing via self.params
4. Differences between shared data and parameters
"""

from pocketflow import BatchFlow, Flow, Node


class AnalyzeTextNode(Node):
    """Analyze text with batch-specific parameters."""

    def prep(self, shared):
        # Get text from shared store
        text = shared.get("text", "")

        # Get analysis parameters from self.params (set by BatchFlow)
        analysis_type = self.params.get("analysis_type", "basic")
        min_length = self.params.get("min_length", 0)

        print(f"  Preparing {analysis_type} analysis for text: '{text[:30]}...'")

        return {"text": text, "analysis_type": analysis_type, "min_length": min_length}

    def exec(self, data):
        # Simulate different analysis based on type
        text = data["text"]
        analysis_type = data["analysis_type"]

        if analysis_type == "sentiment":
            result = {"sentiment": "positive", "score": 0.8}
        elif analysis_type == "entities":
            result = {"entities": ["Python", "BatchFlow", "PocketFlow"]}
        elif analysis_type == "keywords":
            result = {"keywords": ["example", "batch", "processing"]}
        else:
            result = {"basic": len(text.split())}

        return result

    def post(self, shared, prep_res, exec_res):
        # Store individual analysis result
        analysis_type = prep_res["analysis_type"]
        shared[f"{analysis_type}_result"] = exec_res

        # Also accumulate in a list (pattern for collecting across batch runs)
        if "all_analyses" not in shared:
            shared["all_analyses"] = []

        shared["all_analyses"].append({"type": analysis_type, "result": exec_res})

        return "default"


class FormatResultsNode(Node):
    """Format analysis results based on output format parameter."""

    def prep(self, shared):
        # Get accumulated results
        all_analyses = shared.get("all_analyses", [])

        # Get format from params
        output_format = self.params.get("output_format", "json")

        return {"analyses": all_analyses, "format": output_format}

    def exec(self, data):
        analyses = data["analyses"]
        output_format = data["format"]

        if output_format == "markdown":
            result = "# Analysis Results\n\n"
            for analysis in analyses:
                result += f"## {analysis['type'].title()}\n"
                result += f"```\n{analysis['result']}\n```\n\n"
        elif output_format == "plain":
            result = "Analysis Results:\n"
            for analysis in analyses:
                result += f"- {analysis['type']}: {analysis['result']}\n"
        else:  # json
            result = {"analyses": analyses}

        return result

    def post(self, shared, prep_res, exec_res):
        shared["formatted_output"] = exec_res

        # Track which format was used
        if "formats_used" not in shared:
            shared["formats_used"] = []
        shared["formats_used"].append(prep_res["format"])

        return "complete"


class MultiAnalysisBatchFlow(BatchFlow):
    """Run multiple analyses with different parameters."""

    def prep(self, shared):
        """
        Important: BatchFlow prep returns parameter dictionaries,
        NOT the data to process. The data stays in shared store.
        """

        # Get configuration for what analyses to run
        analyses_config = shared.get("analyses_to_run", [])

        # Return list of parameter configurations
        # Each dict will be merged with self.params for the subflow
        param_sets = []

        for config in analyses_config:
            param_sets.append({
                "analysis_type": config["type"],
                "min_length": config.get("min_length", 0),
                "output_format": config.get("format", "json"),
            })

        print(f"Prepared {len(param_sets)} analysis configurations")
        return param_sets

    def post(self, shared, prep_res, exec_res):
        """Aggregate results after all batch runs complete."""

        print("\n=== Batch Analysis Complete ===")
        print(f"Ran {len(prep_res)} analyses")
        print(f"Formats used: {shared.get('formats_used', [])}")

        # Could do final aggregation here
        all_analyses = shared.get("all_analyses", [])
        shared["summary"] = {
            "total_analyses": len(all_analyses),
            "types_run": [a["type"] for a in all_analyses],
            "has_results": all(a.get("result") for a in all_analyses),
        }

        return "batch_done"


def demonstrate_shared_store_behavior():
    """Show how shared store persists across batch iterations."""

    class CounterNode(Node):
        def exec(self, prep_res):
            # Access batch-specific parameter
            increment = self.params.get("increment", 1)
            return increment

        def post(self, shared, prep_res, exec_res):
            # Shared store persists across batch runs
            if "counter" not in shared:
                shared["counter"] = 0

            shared["counter"] += exec_res

            # Also track individual increments
            if "increments" not in shared:
                shared["increments"] = []
            shared["increments"].append(exec_res)

            print(f"  Counter now at: {shared['counter']} (added {exec_res})")
            return "default"

    class CounterBatchFlow(BatchFlow):
        def prep(self, shared):
            # Return different increment values as parameters
            return [{"increment": 1}, {"increment": 5}, {"increment": 10}, {"increment": 3}]

        def post(self, shared, prep_res, exec_res):
            print(f"\nFinal counter: {shared.get('counter', 0)}")
            print(f"Increments applied: {shared.get('increments', [])}")
            return "done"

    # Create and run
    counter_flow = CounterBatchFlow(start=CounterNode())
    shared = {"initial_value": 0}

    print("\nDemonstrating shared store persistence:")
    counter_flow.run(shared)

    return shared


def main():
    """Complete example of BatchFlow usage."""

    # Create the analysis workflow
    analyze = AnalyzeTextNode()
    format_results = FormatResultsNode()
    analyze >> format_results

    # Create flow and batch flow
    analysis_flow = Flow(start=analyze)
    batch_analyzer = MultiAnalysisBatchFlow(start=analysis_flow)

    # Prepare shared data
    shared_data = {
        # The text to analyze (stays in shared store)
        "text": "PocketFlow is a powerful framework for building LLM applications. "
        "It uses nodes and flows to create complex workflows with ease.",
        # Configuration for batch runs (used by BatchFlow.prep)
        "analyses_to_run": [
            {"type": "sentiment", "format": "json"},
            {"type": "entities", "format": "markdown"},
            {"type": "keywords", "format": "plain"},
            {"type": "basic", "min_length": 10, "format": "json"},
        ],
    }

    # Run the batch flow
    print("Starting batch analysis...")
    result = batch_analyzer.run(shared_data)

    print(f"\nBatch result: {result}")
    print(f"\nFinal summary: {shared_data.get('summary', {})}")
    print(f"\nAll analyses: {shared_data.get('all_analyses', [])}")

    # Show shared store persistence
    print("\n" + "=" * 60)
    demonstrate_shared_store_behavior()


if __name__ == "__main__":
    main()
