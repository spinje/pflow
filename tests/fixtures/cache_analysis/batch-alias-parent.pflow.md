# Batch Alias Parent

Fixture for cache-analysis tests where a parent workflow batches child workflow calls and passes `${item.field}`.

## Inputs

### items

Batch items.

- type: list

## Steps

### fanout

Call the child workflow once per item.

- type: workflow
- workflow: ./child.pflow.md
- inputs:
    brief: ${item.concept_brief}
    topic: Batch alias propagation
- batch:
    items: ${items}
    as: item
