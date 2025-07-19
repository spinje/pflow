"""
Examples of Enhanced Interface Format for pflow nodes.

This file contains working examples of how to write docstrings using the
Enhanced Interface Format. These examples can be used as templates for
creating new nodes or migrating existing ones.
"""

from pocketflow import Node


# Example 1: Simple Node with Basic Types
class FileReaderNode(Node):
    """
    Read content from a file with line numbers.

    Interface:
    - Reads: shared["file_path"]: str  # Path to the file to read
    - Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)
    - Writes: shared["content"]: str  # File contents with line numbers
    - Writes: shared["line_count"]: int  # Total number of lines
    - Writes: shared["error"]: str  # Error message if read failed
    - Params: validate_exists: bool  # Check file exists before reading (default: true)
    - Actions: default (success), error (file not found or read error)
    """

    def exec(self, prep_res):
        # Implementation would go here
        pass


# Example 2: Node with Structured Output
class GitHubIssueNode(Node):
    """
    Fetch GitHub issue data with full metadata.

    Interface:
    - Reads: shared["issue_number"]: int  # Issue number to fetch
    - Reads: shared["repo"]: str  # Repository name (owner/repo format)
    - Writes: shared["issue_data"]: dict  # Complete issue information
        - number: int  # Issue number
        - title: str  # Issue title
        - body: str  # Issue description
        - state: str  # Issue state (open, closed)
        - user: dict  # Issue author
          - login: str  # GitHub username
          - id: int  # User ID
          - avatar_url: str  # Profile picture URL
        - labels: list  # Issue labels
          - name: str  # Label name
          - color: str  # Label color (hex)
          - description: str  # Label description
        - milestone: dict  # Milestone info (may be null)
          - id: int  # Milestone ID
          - title: str  # Milestone title
          - due_on: str  # Due date (ISO format)
    - Writes: shared["error"]: str  # Error message if request failed
    - Params: include_comments: bool  # Include issue comments (default: false)
    - Actions: default (success), error (API error)
    """

    def exec(self, prep_res):
        # Implementation would go here
        pass


# Example 3: Node with Complex Nested Structure
class DataProcessorNode(Node):
    """
    Process and transform data with multiple outputs.

    Interface:
    - Reads: shared["raw_data"]: list  # Array of records to process
    - Reads: shared["config"]: dict  # Processing configuration
        - mode: str  # Processing mode ('fast', 'accurate', 'balanced')
        - filters: list  # Active filters
          - name: str  # Filter name
          - params: dict  # Filter parameters
        - output_format: str  # Output format ('json', 'csv', 'xml')
    - Writes: shared["results"]: list  # Processed results
        - id: str  # Record ID
        - data: dict  # Processed data
          - original: dict  # Original record
          - transformed: dict  # Transformed data
          - metadata: dict  # Processing metadata
            - timestamp: str  # Processing time
            - duration_ms: float  # Processing duration
            - filters_applied: list  # Applied filter names
        - score: float  # Quality score (0.0 - 1.0)
    - Writes: shared["summary"]: dict  # Processing summary
        - total_processed: int  # Number of records processed
        - successful: int  # Successfully processed count
        - failed: int  # Failed processing count
        - average_score: float  # Average quality score
    - Writes: shared["error"]: str  # Error message if processing failed
    - Params: batch_size: int  # Processing batch size (default: 100)
    - Params: timeout_seconds: int  # Maximum processing time (default: 300)
    - Actions: default (success), error (processing failure)
    """

    def exec(self, prep_res):
        # Implementation would go here
        pass


# Example 4: Multi-line Format with Many Inputs
class APIClientNode(Node):
    """
    Make HTTP API calls with comprehensive options.

    Interface:
    - Reads: shared["url"]: str  # API endpoint URL
    - Reads: shared["method"]: str  # HTTP method (GET, POST, PUT, DELETE)
    - Reads: shared["headers"]: dict  # Request headers
    - Reads: shared["body"]: dict  # Request body (for POST/PUT)
    - Reads: shared["query_params"]: dict  # URL query parameters
    - Reads: shared["auth_token"]: str  # Authentication token (optional)
    - Writes: shared["response"]: dict  # API response data
    - Writes: shared["status_code"]: int  # HTTP status code
    - Writes: shared["response_headers"]: dict  # Response headers
    - Writes: shared["error"]: str  # Error message if request failed
    - Params: timeout: int  # Request timeout in seconds (default: 30)
    - Params: retry_count: int  # Number of retries on failure (default: 3)
    - Params: verify_ssl: bool  # Verify SSL certificates (default: true)
    - Actions: default (success), error (request failed), timeout (request timed out)
    """

    def exec(self, prep_res):
        # Implementation would go here
        pass


# Example 5: Demonstrating Exclusive Params Pattern
class FileWriterNode(Node):
    """
    Write content to a file with various options.

    Interface:
    - Reads: shared["content"]: str  # Content to write
    - Reads: shared["file_path"]: str  # Destination file path
    - Writes: shared["success"]: bool  # True if written successfully
    - Writes: shared["bytes_written"]: int  # Number of bytes written
    - Writes: shared["error"]: str  # Error message if write failed
    - Params: append: bool  # Append mode instead of overwrite (default: false)
    - Params: create_dirs: bool  # Create parent directories if needed (default: true)
    - Actions: default (success), error (write failure)
    """

    # Note: content and file_path are NOT in Params because they're already in Reads!
    # This follows the exclusive params pattern - only parameters that aren't inputs
    # should be listed in the Params section.

    def exec(self, prep_res):
        # Implementation would go here
        pass


# Example 6: Migration from Old Format
# Old format (before):
"""
Interface:
- Reads: shared["input1"], shared["input2"]
- Writes: shared["output"], shared["error"]
- Params: input1, input2, extra_param
- Actions: default, error
"""


# Enhanced format (after):
class MigratedNode(Node):
    """
    Example showing migration from old to enhanced format.

    Interface:
    - Reads: shared["input1"]: str  # First input value
    - Reads: shared["input2"]: int  # Second input value
    - Writes: shared["output"]: dict  # Processing result
    - Writes: shared["error"]: str  # Error message if failed
    - Params: extra_param: bool  # Additional parameter (not in Reads)
    - Actions: default (success), error (failure)
    """

    # Notice how inputs are NOT repeated in Params!

    def exec(self, prep_res):
        # Implementation would go here
        pass


# Example 7: Complex Real-World Node
class DataPipelineNode(Node):
    """
    Complete data pipeline with validation, transformation, and storage.

    Interface:
    - Reads: shared["source_data"]: list  # Raw data to process
        - id: str  # Record identifier
        - timestamp: str  # Record timestamp (ISO format)
        - payload: dict  # Record data
          - type: str  # Data type ('user', 'event', 'metric')
          - attributes: dict  # Type-specific attributes
    - Reads: shared["pipeline_config"]: dict  # Pipeline configuration
        - stages: list  # Processing stages in order
          - name: str  # Stage name
          - type: str  # Stage type ('validate', 'transform', 'enrich')
          - config: dict  # Stage-specific configuration
        - error_handling: str  # Error strategy ('stop', 'skip', 'retry')
        - output_options: dict  # Output configuration
          - format: str  # Output format ('json', 'parquet', 'csv')
          - compression: str  # Compression type ('none', 'gzip', 'zstd')
    - Writes: shared["processed_data"]: list  # Successfully processed records
        - original_id: str  # Original record ID
        - processed_timestamp: str  # Processing timestamp
        - data: dict  # Processed data
        - transformations: list  # Applied transformations
          - stage: str  # Stage name
          - type: str  # Transformation type
          - changes: dict  # What changed
    - Writes: shared["failed_records"]: list  # Records that failed processing
        - id: str  # Record ID
        - stage: str  # Stage where failure occurred
        - error: str  # Error description
        - original_data: dict  # Original record for debugging
    - Writes: shared["pipeline_metrics"]: dict  # Pipeline execution metrics
        - start_time: str  # Pipeline start timestamp
        - end_time: str  # Pipeline end timestamp
        - total_duration_ms: float  # Total execution time
        - records_processed: int  # Successfully processed count
        - records_failed: int  # Failed count
        - stages_metrics: list  # Per-stage metrics
          - stage_name: str  # Stage identifier
          - duration_ms: float  # Stage execution time
          - records_in: int  # Input record count
          - records_out: int  # Output record count
    - Writes: shared["error"]: str  # Critical error if pipeline failed
    - Params: validate_schema: bool  # Validate input data schema (default: true)
    - Params: parallel_stages: int  # Number of parallel processing threads (default: 4)
    - Params: memory_limit_mb: int  # Memory limit for processing (default: 1024)
    - Actions: default (all records processed), partial (some failures), error (pipeline failure)
    """

    def exec(self, prep_res):
        # Implementation would go here
        pass


# Example 8: Testing Node with All Supported Types
class TypeDemoNode(Node):
    """
    Demonstrates all supported type annotations.

    Interface:
    - Reads: shared["string_input"]: str  # String type example
    - Reads: shared["integer_input"]: int  # Integer type example
    - Reads: shared["float_input"]: float  # Float type example
    - Reads: shared["boolean_input"]: bool  # Boolean type example
    - Reads: shared["dict_input"]: dict  # Dictionary type example
    - Reads: shared["list_input"]: list  # List type example
    - Reads: shared["any_input"]: any  # Any type (when type is dynamic)
    - Writes: shared["type_summary"]: dict  # Summary of all input types
        - str_length: int  # Length of string input
        - int_doubled: int  # Integer input * 2
        - float_rounded: float  # Float rounded to 2 decimals
        - bool_negated: bool  # Opposite of boolean input
        - dict_keys: list  # List of dictionary keys
        - list_length: int  # Number of items in list
        - any_type: str  # Actual type of any_input
    - Actions: default
    """

    def exec(self, prep_res):
        # Implementation would go here
        pass


# Tips for Writing Enhanced Docstrings:
# 1. Always include type annotations (: type) for all inputs, outputs, and params
# 2. Add descriptive comments after # for each item
# 3. Use multi-line format for better readability
# 4. Document structures with proper indentation (2 or 4 spaces)
# 5. Follow the exclusive params pattern - don't repeat inputs in params
# 6. Include action descriptions in parentheses
# 7. For optional parameters, mention defaults in the description
# 8. Use consistent formatting throughout your codebase
