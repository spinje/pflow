In PocketFlow there's clear separation:

  def post(self, shared, prep_res, exec_res):
      shared['summary'] = exec_res['summary']  # Write data
      return "approved"  # Return action

  But in markdown with a code block:
  result = review_expense(report)
  summary = result.summary
  return 'payment'  # Is this data or action?

  How do we distinguish data from action?

  Option 1: Declared Outputs

  ## review
  type: python
  outputs: [summary, status]  # These get stored in shared store

  ```python
  result = review_expense(report)
  summary = result.summary  # Captured because it's in outputs
  status = result.status      # Captured because it's in outputs

  if status == 'approved':
      return 'payment'  # This is the action
  else:
      return 'rejected'

  payment

  ...

  Variables matching `outputs` are saved. `return` is routing action.

  ## Option 2: Return Tuple

  ```python
  result = review_expense(report)
  data = {
      'summary': result.summary,
      'status': result.status
  }

  if result.approved:
      return data, 'payment'  # (data dict, action string)
  else:
      return data, 'rejected'

  Option 3: Explicit Action Call

  result = review_expense(report)
  set_output('summary', result.summary)  # Explicit data
  set_output('status', result.status)

  if result.approved:
      action('payment')  # Explicit routing

  Option 4: Conditions in Metadata

  ## review
  type: python
  outputs: [summary, status]
  routes:
    - if: status == 'approved', then: payment
    - if: status == 'needs_revision', then: revise
    - else: finish

  ```python
  result = review_expense(report)
  summary = result.summary
  status = result.status
  # No explicit return - pflow evaluates conditions

  **My instinct: Option 1** (declared outputs) is clearest. Separates data declaration from routing logic.

  This needs to be explored in detail. These are just some ideas. More need to be evaluated.