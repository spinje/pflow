# Nested Workflow Parameter Passing Examples

## Example 1: Basic Parameter Mapping

### Parent Workflow
```json
{
  "name": "analyze-repository",
  "nodes": [
    {
      "id": "get_repo_info",
      "type": "github-get-repo",
      "params": {
        "owner": "$repo_owner",
        "name": "$repo_name"
      }
    },
    {
      "id": "analyze_issues",
      "type": "workflow",
      "params": {
        "workflow_ref": "workflows/issue-analyzer.json",
        "param_mapping": {
          "repository": "$repo_info.full_name",
          "issue_count": "$repo_info.open_issues_count",
          "api_token": "$github_token"
        },
        "output_mapping": {
          "summary": "issue_analysis",
          "critical_count": "critical_issues"
        }
      }
    }
  ],
  "edges": [
    {"source": "get_repo_info", "target": "analyze_issues"}
  ]
}
```

### Child Workflow (issue-analyzer.json)
```json
{
  "name": "issue-analyzer",
  "nodes": [
    {
      "id": "list_issues",
      "type": "github-list-issues",
      "params": {
        "repo": "$repository",
        "limit": "$issue_count"
      }
    },
    {
      "id": "analyze",
      "type": "llm",
      "params": {
        "prompt": "Analyze these issues and identify critical ones: $issues"
      }
    }
  ]
}
```

### Runtime Execution Flow

1. **Parent Initial Params** (from planner):
   ```json
   {
     "repo_owner": "pflow",
     "repo_name": "pflow",
     "github_token": "ghp_xxxxx"
   }
   ```

2. **After get_repo_info executes**, parent shared store:
   ```json
   {
     "repo_info": {
       "full_name": "pflow/pflow",
       "open_issues_count": 42,
       "stars": 1000
     }
   }
   ```

3. **WorkflowNode resolves param_mapping**:
   ```json
   {
     "repository": "pflow/pflow",      // from $repo_info.full_name
     "issue_count": 42,                // from $repo_info.open_issues_count
     "api_token": "ghp_xxxxx"          // from initial_params
   }
   ```

4. **Child workflow executes** with its own shared store and the resolved params

5. **After child completes**, output mapping updates parent:
   ```json
   {
     "repo_info": { ... },
     "issue_analysis": "Found 5 critical issues...",
     "critical_issues": 5
   }
   ```

## Example 2: Complex Object Mapping

### Parent Workflow
```json
{
  "nodes": [
    {
      "id": "process_data",
      "type": "workflow",
      "params": {
        "workflow_ref": "etl-pipeline.json",
        "param_mapping": {
          "source_config": {
            "type": "database",
            "connection": "$db_connection_string",
            "query": "$user_query"
          },
          "transform_options": {
            "format": "$output_format",
            "filters": "$data_filters",
            "batch_size": 1000
          },
          "destination": "$output_path"
        }
      }
    }
  ]
}
```

### Resolution Example
Parent context:
```json
{
  "db_connection_string": "postgresql://localhost/mydb",
  "user_query": "SELECT * FROM users WHERE active = true",
  "output_format": "parquet",
  "data_filters": ["remove_nulls", "validate_emails"],
  "output_path": "/data/processed/users.parquet"
}
```

Child receives:
```json
{
  "source_config": {
    "type": "database",
    "connection": "postgresql://localhost/mydb",
    "query": "SELECT * FROM users WHERE active = true"
  },
  "transform_options": {
    "format": "parquet",
    "filters": ["remove_nulls", "validate_emails"],
    "batch_size": 1000
  },
  "destination": "/data/processed/users.parquet"
}
```

## Example 3: Iterative Processing with Child Workflows

### Parent Workflow
```json
{
  "nodes": [
    {
      "id": "list_files",
      "type": "list-directory",
      "params": {
        "path": "$input_directory",
        "pattern": "*.csv"
      }
    },
    {
      "id": "process_each",
      "type": "foreach",
      "params": {
        "items": "$files",
        "workflow": {
          "workflow_ref": "csv-processor.json",
          "param_mapping": {
            "input_file": "$item.path",
            "output_file": "$output_dir/$item.name.parquet",
            "schema": "$csv_schema"
          },
          "output_mapping": {
            "rows_processed": "processed_counts[]"
          }
        }
      }
    }
  ]
}
```

### Execution Pattern
For each file in the list:
1. Create param mapping with current `$item`
2. Execute child workflow with mapped params
3. Collect outputs into parent array

## Example 4: Conditional Parameter Mapping

### Advanced Mapping (Future Enhancement)
```json
{
  "param_mapping": {
    // Static values
    "version": "1.0",

    // Simple templates
    "user_id": "$current_user.id",

    // Nested paths
    "api_key": "$config.apis.github.key",

    // String interpolation
    "message": "Processing file $filename at $timestamp",

    // Conditional (future)
    "log_level": "$debug_mode ? 'DEBUG' : 'INFO'",

    // Array access (if supported)
    "first_tag": "$tags[0]",

    // Default values (future)
    "timeout": "$custom_timeout || 30"
  }
}
```

## Example 5: Storage Mode Differences

### Isolated Mode (Default)
```json
{
  "storage_mode": "isolated",
  "param_mapping": {
    "data": "$processed_data"
  }
}
```
Child workflow ONLY sees:
```json
{
  "data": "...value from parent..."
}
```

### Scoped Mode
```json
{
  "storage_mode": "scoped",
  "scope_prefix": "child_",
  "param_mapping": {
    "config": "$child_config"
  }
}
```
Child sees filtered parent storage:
```json
{
  "child_config": {...},
  "child_data": {...}
  // No access to parent's other keys
}
```

## Example 6: Error Handling

### Template Resolution Errors
```json
{
  "param_mapping": {
    "required_value": "$missing_key"  // Error if not found
  }
}
```

Error message:
```
WorkflowNode execution failed: Template resolution error
- Parameter 'required_value': Cannot resolve '$missing_key'
- Available keys in context: [repo_info, user_id, ...]
- Suggestion: Check if previous nodes set this value
```

### Validation Errors
```json
{
  "param_mapping": {
    "count": "$string_value"  // Type mismatch
  }
}
```

Future validation:
```
Parameter type mismatch in workflow 'analyzer':
- Parameter 'count' expects: number
- Received: string ("hello")
- From mapping: $string_value
```

## Example 7: Best Practices

### Good: Explicit, Clear Mappings
```json
{
  "param_mapping": {
    "github_repo": "$repo_name",
    "github_token": "$auth.github_token",
    "max_results": 100
  }
}
```

### Bad: Implicit Assumptions
```json
{
  "param_mapping": {
    // Assuming child knows about parent's structure
    "data": "$"  // What data?
  }
}
```

### Good: Defensive Mapping
```json
{
  "param_mapping": {
    "input_data": "$processed_data || $raw_data",  // Fallback
    "retries": "$config.retries || 3"              // Default
  }
}
```

## Summary

These examples demonstrate:
1. **Flexibility**: From simple values to complex objects
2. **Safety**: Isolated storage prevents accidents
3. **Power**: Full template resolution capabilities
4. **Clarity**: Explicit mappings document data flow
5. **Reusability**: Child workflows remain independent

The design enables powerful workflow composition while maintaining the simplicity and predictability that pflow users expect.
