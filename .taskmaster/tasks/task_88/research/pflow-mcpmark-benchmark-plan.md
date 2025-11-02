# pflow Benchmarking Implementation Plan: MCPMark Evaluation

**Objective:** Demonstrate pflow's cost and time savings through compile-once-reuse approach using MCPMark benchmark with self-published, reproducible results.

**Timeline:** 7 days
**Target:** Engineers and skeptical buyers evaluating workflow optimization solutions

---

## Executive Summary

### What We're Proving

**Hypothesis:** pflow's compile-once-reuse approach reduces cost and time for repeated MCP workflow executions compared to agent-only execution.

**Method:** Run MCPMark's 127 tasks in two modes:
1. **First-run mode** - Agent plans + pflow compiles + executes (baseline)
2. **Reuse mode** - Load compiled workflow + execute (no LLM inference)

**Expected Results:**
- 90-95% cost reduction on reuse runs
- 60-70% time reduction on reuse runs
- Identical or higher success rates (deterministic execution)

### Why MCPMark

- 127 expert-designed MCP tasks across 5 real environments
- Academic backing (EVAL SYS, LobeHub, NUS)
- Open source + reproducible
- Cost and performance metrics built-in
- MCP-native (matches pflow's target use case)

---

## Phase 1: Prerequisites & Setup (Days 1-2)

### Day 1 Morning: Environment Setup

**Clone MCPMark:**
```bash
git clone https://github.com/eval-sys/mcpmark.git
cd mcpmark
git checkout <latest-stable-tag>  # Record exact commit SHA
```

**Install dependencies:**
```bash
pip install -r requirements.txt --break-system-packages
```

**Configure baseline services:**
```bash
# Start with filesystem tasks (zero-config)
# Defer GitHub/Notion/PostgreSQL/Playwright until Day 2
```

**Test MCPMark baseline:**
```bash
# Run 3 filesystem tasks to verify installation
python run.py --task filesystem_001 --model claude-sonnet-3-5
```

**Success criteria:**
- [ ] MCPMark runs successfully on local machine
- [ ] Filesystem tasks execute and produce results
- [ ] Result format documented (JSON schema captured)

### Day 1 Afternoon: pflow MCP Server Packaging

**Current state assessment:**
- [ ] Is pflow already an MCP server? (Check existing architecture)
- [ ] What format does pflow currently use for workflow storage?
- [ ] Can pflow execute workflows without LLM calls?

**If pflow is NOT yet an MCP server:**

Create minimal MCP server wrapper:
```python
# pflow_mcp_server.py
from mcp.server import Server
import pflow

server = Server("pflow")

@server.call_tool()
async def execute_workflow(workflow_id: str, parameters: dict):
    """Execute a compiled pflow workflow"""
    workflow = pflow.load_workflow(workflow_id)
    result = await workflow.execute(parameters)
    return result

# Additional tool endpoints as needed
```

**If pflow IS already an MCP server:**
- Document how to invoke it via MCPMark
- Test basic invocation flow

**Success criteria:**
- [ ] pflow can be invoked as an MCP server
- [ ] pflow can save compiled workflows to disk
- [ ] pflow can load and execute saved workflows
- [ ] Workflows execute deterministically (same input → same output)

### Day 2 Morning: MCPMark Service Configuration

**Configure remaining MCPMark environments:**

**GitHub (23 tasks):**
```bash
export GITHUB_TOKEN=<your_token>
export GITHUB_OWNER=<test_org>
export GITHUB_REPO=<test_repo>
```

**Notion (28 tasks):**
```bash
export NOTION_TOKEN=<integration_token>
export NOTION_DATABASE_ID=<test_database>
```

**PostgreSQL (21 tasks):**
```bash
docker run -d \
  -e POSTGRES_PASSWORD=test \
  -p 5432:5432 \
  postgres:latest

export POSTGRES_CONNECTION_STRING=postgresql://postgres:test@localhost:5432/testdb
```

**Playwright (25 tasks):**
```bash
playwright install
```

**Test one task from each environment:**
```bash
python run.py --task github_001 --model claude-sonnet-3-5
python run.py --task notion_001 --model claude-sonnet-3-5
python run.py --task postgres_001 --model claude-sonnet-3-5
python run.py --task playwright_001 --model claude-sonnet-3-5
```

**Success criteria:**
- [ ] All 5 MCPMark environments operational
- [ ] Credentials configured correctly
- [ ] Sample task from each environment runs successfully

### Day 2 Afternoon: Integration Architecture

**Design pflow integration with MCPMark:**

**Option A: Wrapper Script (Recommended)**
```python
# run_pflow_benchmark.py

def run_first_mode(task_id):
    """Agent plans + pflow compiles + executes"""
    # 1. Let agent analyze task
    # 2. Agent generates workflow plan
    # 3. pflow compiles plan to workflow_id
    # 4. Execute workflow
    # 5. Save compiled workflow to ./workflows/{task_id}.json
    return {
        'success': bool,
        'cost_usd': float,
        'time_ms': int,
        'tokens_in': int,
        'tokens_out': int,
        'workflow_id': str
    }

def run_reuse_mode(task_id, workflow_id):
    """Load compiled workflow + execute (no LLM)"""
    # 1. Load workflow from ./workflows/{task_id}.json
    # 2. Execute deterministically
    # 3. Track execution time only (no LLM cost)
    return {
        'success': bool,
        'cost_usd': 0.0,  # No LLM calls
        'time_ms': int,
        'tokens_in': 0,
        'tokens_out': 0,
        'workflow_id': str
    }
```

**Option B: Modify MCPMark Runner**
- Fork mcpmark repository
- Add `--mode first|reuse` flag to run.py
- Modify agent executor to use pflow
- Store compiled workflows between runs

**Decision point:** Choose Option A (cleaner separation) or Option B (tighter integration)

**Success criteria:**
- [ ] Architecture documented
- [ ] Integration approach chosen
- [ ] Proof-of-concept works on 1 task

---

## Phase 2: Benchmark Execution (Days 3-5)

### Day 3: First-Run Mode Execution

**Run all 127 tasks in first-run mode:**

```bash
# Run with logging and error handling
python run_pflow_benchmark.py \
  --mode first \
  --tasks all \
  --model claude-sonnet-3-5 \
  --output-dir ./results/first_run \
  --save-workflows ./workflows
```

**Expected output structure:**
```
results/first_run/
├── filesystem/
│   ├── task_001.json
│   ├── task_002.json
│   └── ...
├── github/
├── notion/
├── postgres/
├── playwright/
└── summary.json

workflows/
├── filesystem_001.json
├── filesystem_002.json
└── ...
```

**Handle failures:**
- Tasks may fail due to API limits, timeouts, or task complexity
- Log all failures with error messages
- Continue with remaining tasks
- Document failure patterns

**Monitor metrics:**
```bash
# Watch costs accumulate
tail -f results/first_run/summary.json

# Track progress
echo "Completed: $(ls results/first_run/*/*.json | wc -l) / 127"
```

**Success criteria:**
- [ ] ≥100 tasks complete successfully (79%+ success rate)
- [ ] All results saved in structured format
- [ ] Compiled workflows saved for reuse
- [ ] Total cost logged (expect $20-50 for 127 tasks)
- [ ] Execution time per task recorded

### Day 4: Reuse Mode Execution

**Run all 127 tasks in reuse mode (using compiled workflows):**

```bash
python run_pflow_benchmark.py \
  --mode reuse \
  --tasks all \
  --workflows-dir ./workflows \
  --output-dir ./results/reuse
```

**Validation checks:**
- Every task that succeeded in first-run should succeed in reuse
- Success rate should be equal or higher (deterministic execution)
- Cost should be near-zero (only MCP tool execution costs, no LLM)
- Time should be 50-70% faster

**Handle edge cases:**
- Tasks that failed in first-run will have no compiled workflow → skip
- External state changes (GitHub repos modified) → document expected failures
- API rate limits → implement retry logic

**Success criteria:**
- [ ] ≥100 tasks complete successfully in reuse mode
- [ ] Cost per task is <$0.05 (no LLM inference)
- [ ] Time savings of 50-70% observed
- [ ] All results match first-run success/failure patterns

### Day 5: Validation & Quality Assurance

**Compare first-run vs reuse results:**

```python
# validate_results.py

def compare_results():
    first_run = load_results('./results/first_run')
    reuse_run = load_results('./results/reuse')

    for task_id in first_run.keys():
        fr = first_run[task_id]
        rr = reuse_run[task_id]

        # Validate consistency
        assert fr['success'] == rr['success'], f"Success mismatch: {task_id}"

        # Calculate savings
        cost_savings = (fr['cost_usd'] - rr['cost_usd']) / fr['cost_usd'] * 100
        time_savings = (fr['time_ms'] - rr['time_ms']) / fr['time_ms'] * 100

        print(f"{task_id}: Cost savings {cost_savings:.1f}%, Time savings {time_savings:.1f}%")
```

**Statistical analysis:**
- Mean cost savings
- Median cost savings
- Standard deviation (detect outliers)
- Cost savings by environment (filesystem vs GitHub vs Notion, etc.)
- Time savings distribution

**Identify patterns:**
- Which tasks benefit most from reuse?
- Which tasks show minimal savings? (Why?)
- Are there failure cases unique to reuse mode?

**Success criteria:**
- [ ] Validation script runs without assertion errors
- [ ] Cost savings average 90-95%
- [ ] Time savings average 60-70%
- [ ] No unexpected reuse failures (only expected external state changes)

---

## Phase 3: Analysis & Reporting (Day 6)

### Generate Comprehensive Report

**Key metrics to calculate:**

**Aggregate savings:**
```
Total first-run cost: $X
Total reuse cost: $Y
Total savings: $Z ($X - $Y)
Savings percentage: Z/X * 100%

Total first-run time: Xh
Total reuse time: Yh
Time savings: Zh (X - Y)
Time savings percentage: Z/X * 100%
```

**Per-environment breakdown:**
```
Environment    | Tasks | First Cost | Reuse Cost | Savings %
---------------|-------|------------|------------|----------
Filesystem     | 30    | $5.20      | $0.15      | 97.1%
GitHub         | 23    | $8.40      | $0.32      | 96.2%
Notion         | 28    | $7.10      | $0.28      | 96.1%
PostgreSQL     | 21    | $4.80      | $0.18      | 96.3%
Playwright     | 25    | $6.50      | $0.25      | 96.2%
---------------|-------|------------|------------|----------
TOTAL          | 127   | $32.00     | $1.18      | 96.3%
```

**Visualizations to create:**

1. **Cost comparison bar chart**
   - X-axis: Task environments
   - Y-axis: Cost in USD
   - Two bars per environment (first-run vs reuse)

2. **Savings distribution histogram**
   - X-axis: Savings percentage (80-85%, 85-90%, 90-95%, 95-100%)
   - Y-axis: Number of tasks
   - Shows how many tasks achieve each savings tier

3. **Time vs cost scatter plot**
   - X-axis: Time savings %
   - Y-axis: Cost savings %
   - Each point is a task
   - Shows correlation between time and cost savings

4. **Per-task comparison table (top 20 by savings)**
   - Task ID | First Cost | Reuse Cost | Savings % | Time Savings %
   - Sorted by absolute dollar savings

**Report structure:**

```markdown
# pflow Performance Report: MCPMark Benchmark Results

## Executive Summary

pflow achieved **96.3% cost savings** and **65.7% time savings** across 127 MCPMark tasks by compiling workflows on first execution and reusing them on subsequent runs.

[Key charts here]

## Methodology

- Benchmark: MCPMark v1.0 (commit: abc123)
- Model: Claude Sonnet 3.5 ($3/$15 per million tokens)
- Tasks: 127 tasks across 5 MCP environments
- Execution: Ubuntu 24.04, 16GB RAM, [CPU specs]
- Date: [execution dates]

## Results

### Aggregate Performance

[Detailed metrics table]

### Per-Environment Analysis

[Environment breakdown]

### Task-Level Results

[CSV export of all 127 tasks with full metrics]

## Reproduction Instructions

[Step-by-step guide to replicate results]

## Raw Data

All result files available at:
- First-run results: `results/first_run/`
- Reuse results: `results/reuse/`
- Compiled workflows: `workflows/`

[Links to GitHub release with data]

## Conclusion

pflow's compile-once-reuse approach delivers measurable cost and time savings for repeated MCP workflow execution with no loss in success rate or accuracy.

## Appendix

- Full MCPMark task list
- Error analysis
- Environment configuration
- Hardware specifications
```

**Success criteria:**
- [ ] Report written in clear, data-driven language
- [ ] All charts generated and embedded
- [ ] Raw data files prepared for publication
- [ ] Reproduction guide complete and tested

---

## Phase 4: Publication & Documentation (Day 7)

### Create Public Repository

**Repository structure:**

```
pflow-mcpmark-evaluation/
├── README.md                        # Report summary + key findings
├── REPRODUCE.md                     # Step-by-step reproduction guide
├── results/
│   ├── first_run/
│   │   ├── summary.json
│   │   └── [127 task result files]
│   ├── reuse/
│   │   ├── summary.json
│   │   └── [127 task result files]
│   └── analysis.ipynb               # Jupyter notebook with analysis
├── workflows/
│   └── [127 compiled workflow files]
├── charts/
│   ├── cost_comparison.png
│   ├── savings_distribution.png
│   ├── time_vs_cost_scatter.png
│   └── per_environment_breakdown.png
├── scripts/
│   ├── run_pflow_benchmark.py       # Main benchmark runner
│   ├── validate_results.py          # Validation script
│   └── generate_report.py           # Report generation
├── docker-compose.yml               # One-command reproduction setup
└── LICENSE                          # MIT or Apache-2.0
```

**README.md key sections:**

```markdown
# pflow MCPMark Evaluation Results

**TL;DR:** pflow reduces MCP workflow costs by 96.3% and execution time by 65.7% through compile-once-reuse architecture.

## Quick Results

[Embed key chart]

| Metric | First Run | Reuse | Savings |
|--------|-----------|-------|---------|
| Total Cost | $32.00 | $1.18 | 96.3% |
| Avg Time/Task | 35s | 12s | 65.7% |
| Success Rate | 94% | 94% | 0% |

[Link to full report]

## Verify These Results

```bash
git clone https://github.com/[org]/pflow-mcpmark-evaluation
cd pflow-mcpmark-evaluation
./reproduce.sh  # Runs full benchmark, takes ~4 hours
```

[Link to REPRODUCE.md]

## About This Benchmark

We used MCPMark (https://github.com/eval-sys/mcpmark), an open-source MCP benchmark maintained by EVAL SYS, LobeHub, and NUS.

MCPMark version: v1.0 (commit: abc123)
Execution date: [date]
Hardware: [specs]
```

**REPRODUCE.md guide:**

```markdown
# Reproduction Guide

## Prerequisites

- Docker + Docker Compose
- 16GB RAM minimum
- Anthropic API key ($50 budget for full run)
- GitHub account (for GitHub tasks)
- Notion account (for Notion tasks)

## One-Command Reproduction

```bash
export ANTHROPIC_API_KEY=your_key
export GITHUB_TOKEN=your_token
export NOTION_TOKEN=your_token

docker-compose up
```

This will:
1. Set up all 5 MCPMark environments
2. Run 127 tasks in first-run mode
3. Run 127 tasks in reuse mode
4. Generate comparison report
5. Output results to ./results/

Expected runtime: 4-6 hours
Expected cost: $30-50

## Step-by-Step Manual Reproduction

[Detailed steps matching Days 1-6 above]

## Verify Results Match Ours

```bash
python scripts/compare_results.py \
  --published results/summary.json \
  --yours your_results/summary.json \
  --tolerance 0.05  # Allow 5% variance due to API timing
```

## Common Issues

[Troubleshooting guide]
```

### Optional: Video Demonstration

**Record 5-minute video showing:**
1. Benchmark running (time-lapse)
2. Cost accumulation in both modes
3. Final results comparison
4. Key takeaway: "96% cost savings, identical success rate"

Upload to YouTube with:
- Title: "pflow vs Standard MCP: 96% Cost Reduction on MCPMark Benchmark"
- Description with links to repo and full report
- Tags: MCP, workflow optimization, LLM cost reduction

### Publish

**Where to publish:**
1. **GitHub repository** - Complete results + reproduction guide
2. **Blog post / technical write-up** - Summary with embedded charts
3. **Twitter/LinkedIn** - Short summary with key chart
4. **Show HN / r/MachineLearning** - Link to GitHub repo
5. **MCPMark team** - Email hello@evalsys.org with results link

**Publish checklist:**
- [ ] GitHub repository public
- [ ] README and REPRODUCE.md complete
- [ ] All result files uploaded
- [ ] Docker reproduction tested on clean VM
- [ ] Blog post written and published
- [ ] Social media posts scheduled
- [ ] MCPMark team notified

---

## Success Criteria (Overall)

### Minimum Viable Result

- [ ] ≥100/127 tasks completed in both modes
- [ ] ≥85% average cost savings
- [ ] ≥50% average time savings
- [ ] Success rates within 5% between modes
- [ ] Results publicly available and reproducible

### Stretch Goals

- [ ] 120+/127 tasks completed
- [ ] ≥95% average cost savings
- [ ] ≥65% average time savings
- [ ] Featured on MCPMark website or leaderboard
- [ ] 100+ GitHub stars within first month
- [ ] 3+ independent reproductions by community

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| MCPMark API changes | Low | High | Pin to specific commit SHA, fork if needed |
| API rate limits (Claude/GitHub/Notion) | Medium | Medium | Implement exponential backoff, request rate increases |
| Task failures exceed 30% | Low | High | Start with small subset, debug before full run |
| Results not compelling (savings <80%) | Low | High | Re-evaluate pflow architecture, may need optimization |
| Reproduction fails for others | Medium | High | Test Docker setup on clean VM before publishing |
| Cost overruns ($100+) | Low | Medium | Monitor costs during execution, set budget alerts |

---

## Estimated Costs

### Compute
- Cloud VM (if needed): $20-40 for week
- Local development: $0

### API Usage
- Claude API (first-run): $30-50 for 127 tasks
- Claude API (reuse): $1-2 for 127 tasks
- GitHub/Notion/Playwright APIs: $0 (within free tiers)

### Total Budget: $50-100

---

## Deliverables Checklist

- [ ] Public GitHub repository with results
- [ ] Comprehensive report (Markdown + PDF)
- [ ] All 254 result files (127 first-run + 127 reuse)
- [ ] 127 compiled workflow files
- [ ] Analysis notebook (Jupyter)
- [ ] 4+ data visualizations
- [ ] Reproduction guide tested on clean environment
- [ ] Docker Compose setup for one-command reproduction
- [ ] Blog post or technical write-up
- [ ] Social media posts
- [ ] Video demonstration (optional)
- [ ] Email to MCPMark team with results

---

## Next Steps After Completion

### Short-term (Week 2)
1. Monitor community response
2. Respond to questions and reproduction attempts
3. Fix any bugs discovered during reproduction
4. Add requested features (e.g., different models, custom tasks)

### Medium-term (Month 1)
1. Add more benchmarks (HAL, AgentBench, etc.)
2. Optimize pflow based on failure analysis
3. Create case studies from specific high-value tasks
4. Consider submitting paper to workshop (e.g., NeurIPS MLSys)

### Long-term (Quarter 1)
1. Track pflow adoption metrics
2. Collect user-submitted benchmarks
3. Build public leaderboard for workflow optimization tools
4. Engage with MCPMark team on official integration

---

## Contact & Support

**Questions during implementation:**
- pflow team: [internal contact]
- MCPMark team: hello@evalsys.org
- Benchmark setup issues: [create GitHub issue]

**After publication:**
- GitHub Issues: [repository link]
- Email: [public contact]
- Discord/Slack: [community link if exists]

---

**Document Version:** 1.0
**Last Updated:** [Date]
**Owner:** [Your name/team]
**Status:** Ready for execution
