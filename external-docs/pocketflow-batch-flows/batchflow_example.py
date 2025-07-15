#!/usr/bin/env python3
"""
BatchFlow Example: Processing Multiple Documents with Subflows

This example demonstrates how to use BatchFlow to run a complete workflow
multiple times with different parameters. Each document goes through:
1. Loading content
2. Extracting keywords
3. Generating summary
4. Saving results
"""

from pocketflow import BatchFlow, Flow, Node


# Individual nodes for processing a single document
class LoadDocumentNode(Node):
    """Load document content based on params."""

    def exec(self, prep_res):
        # Access parameters set by BatchFlow
        doc_path = self.params.get("path")
        doc_id = self.params.get("id")

        # Simulate loading document
        content = f"Content of document {doc_id} from {doc_path}"
        return content

    def post(self, shared, prep_res, exec_res):
        shared["content"] = exec_res
        shared["doc_id"] = self.params.get("id")
        return "default"


class ExtractKeywordsNode(Node):
    """Extract keywords from document content."""

    def prep(self, shared):
        return shared.get("content", "")

    def exec(self, content):
        # Simulate keyword extraction
        keywords = ["keyword1", "keyword2", "keyword3"]
        return keywords

    def post(self, shared, prep_res, exec_res):
        shared["keywords"] = exec_res
        return "default"


class GenerateSummaryNode(Node):
    """Generate summary based on content and keywords."""

    def prep(self, shared):
        return {"content": shared.get("content", ""), "keywords": shared.get("keywords", [])}

    def exec(self, data):
        # Simulate summary generation
        summary = f"Summary of document with keywords: {', '.join(data['keywords'])}"
        return summary

    def post(self, shared, prep_res, exec_res):
        shared["summary"] = exec_res
        return "default"


class SaveResultsNode(Node):
    """Save processing results."""

    def prep(self, shared):
        return {
            "doc_id": shared.get("doc_id"),
            "keywords": shared.get("keywords", []),
            "summary": shared.get("summary", ""),
        }

    def exec(self, results):
        # Simulate saving results
        print(f"Saving results for document {results['doc_id']}:")
        print(f"  Keywords: {results['keywords']}")
        print(f"  Summary: {results['summary']}")
        return f"Results saved for {results['doc_id']}"

    def post(self, shared, prep_res, exec_res):
        shared["save_status"] = exec_res
        # Store results in a list that persists across batch runs
        if "all_results" not in shared:
            shared["all_results"] = []
        shared["all_results"].append({"doc_id": prep_res["doc_id"], "status": exec_res})
        return "complete"


class DocumentProcessingBatchFlow(BatchFlow):
    """BatchFlow that processes multiple documents."""

    def prep(self, shared):
        """Return list of parameter dictionaries for each document."""
        documents = shared.get("documents", [])

        # Create parameter dict for each document
        # These params will be passed to nodes via self.params
        return [{"id": doc["id"], "path": doc["path"], "priority": doc.get("priority", "normal")} for doc in documents]

    def post(self, shared, prep_res, exec_res):
        """Post-process after all documents are processed."""
        print("\n=== Batch Processing Complete ===")
        print(f"Processed {len(prep_res)} documents")

        # Access aggregated results
        all_results = shared.get("all_results", [])
        for result in all_results:
            print(f"  - {result['doc_id']}: {result['status']}")

        return "batch_complete"


def create_document_processing_flow():
    """Create the single document processing flow."""
    # Create nodes
    load = LoadDocumentNode()
    extract = ExtractKeywordsNode()
    summarize = GenerateSummaryNode()
    save = SaveResultsNode()

    # Connect nodes
    load >> extract >> summarize >> save

    # Create flow starting with load node
    return Flow(start=load)


def main():
    """Example usage of BatchFlow."""

    # Create the single document processing flow
    single_doc_flow = create_document_processing_flow()

    # Create BatchFlow with the single doc flow as the start node
    batch_processor = DocumentProcessingBatchFlow(start=single_doc_flow)

    # Prepare shared data with multiple documents
    shared_data = {
        "documents": [
            {"id": "doc1", "path": "/path/to/doc1.txt", "priority": "high"},
            {"id": "doc2", "path": "/path/to/doc2.txt"},
            {"id": "doc3", "path": "/path/to/doc3.txt", "priority": "low"},
        ]
    }

    # Run the batch flow
    print("Starting batch processing...")
    result = batch_processor.run(shared_data)

    print(f"\nFinal result: {result}")
    print(f"All results: {shared_data.get('all_results', [])}")


# Alternative approach: Using regular Flow with dynamic invocation
class ProcessAllDocumentsNode(Node):
    """Alternative: Process all documents using dynamic flow invocation."""

    def prep(self, shared):
        return shared.get("documents", [])

    def exec(self, documents):
        results = []

        # Create the processing flow once
        doc_flow = create_document_processing_flow()

        for doc in documents:
            # Create fresh shared data for each document
            doc_shared = {
                "doc_params": doc  # Pass document info differently
            }

            # Manually set params on the first node
            doc_flow.start_node.set_params(doc)

            # Run the flow
            doc_flow.run(doc_shared)

            # Collect results
            results.append({
                "doc_id": doc["id"],
                "summary": doc_shared.get("summary"),
                "keywords": doc_shared.get("keywords"),
            })

        return results

    def post(self, shared, prep_res, exec_res):
        shared["batch_results"] = exec_res
        return "complete"


if __name__ == "__main__":
    main()

    print("\n" + "=" * 50 + "\n")
    print("Alternative approach using dynamic flow invocation:")

    # Alternative approach
    alt_processor = ProcessAllDocumentsNode()
    alt_shared = {
        "documents": [
            {"id": "doc1", "path": "/path/to/doc1.txt"},
            {"id": "doc2", "path": "/path/to/doc2.txt"},
        ]
    }

    alt_processor.run(alt_shared)
    print(f"Alternative results: {alt_shared.get('batch_results', [])}")
