# Support Ticket Triage

Reads an incoming support ticket, has an LLM condense it into a two-sentence summary,
then a small Python step decides whether it is urgent — urgent tickets escalate to the
on-call engineer, routine ones queue for the next business day. Written to be narrated:
each step is one clear sentence of work.

## Steps

### fetch-ticket

Pull the newest ticket text from the support inbox (mocked with a sample ticket here).

- type: shell

```shell command
printf 'Subject: App crashes on export\nCustomer: acme-corp (enterprise)\nBody: Since this morning, exporting any report crashes the app immediately. Our quarterly review is tomorrow.'
```

### summarize-ticket

Condense the raw ticket into a two-sentence summary a triager can read at a glance.

- type: llm

```text prompt
Summarize this support ticket in two sentences, keeping the customer tier and impact:

${fetch-ticket.stdout}
```

### assess-urgency

Decide from the summary whether this ticket is urgent (crash, outage, enterprise) or routine.

- type: code
- inputs: { summary: "${summarize-ticket.response}" }

```python code
summary: str

signals = ["crash", "outage", "down", "enterprise"]
if any(word in summary.lower() for word in signals):
    next: str = "escalate"
else:
    next: str = "queue-routine"
result: str = next
```

### escalate

Urgent path: page the on-call engineer with the summary.

- type: shell
- next: end

```shell command
echo "PAGE ON-CALL: ${summarize-ticket.response}"
```

### queue-routine

Routine path: add the ticket to tomorrow's queue and stand down.

- type: shell
- next: end

```shell command
echo "Queued for next business day."
```

## Outputs

### triage_summary

The LLM's two-sentence ticket summary — what the triager reads first.

- source: ${summarize-ticket.response}
- stdout: true
