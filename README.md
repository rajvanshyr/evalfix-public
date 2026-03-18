# evalfix

**We help your Agent get smarter every time it fails.**

evalfix tests your prompt, identifies failures, and uses an AI optimizer to fix them — automatically.

---

## How it works

```
evalfix run      →  run all evals, see pass/fail
evalfix fix      →  find what's failing, AI-generate a fix, apply it
evalfix report   →  view last run in the terminal or as HTML
evalfix history  →  see score trends across all runs
```

---

## Installation

**Prerequisites:** Python 3.11+, an [Anthropic API key](https://console.anthropic.com/)

```bash
pip install evalfix
```

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Add this to your `~/.zshrc` or `~/.bashrc` to avoid setting it every session.

---

## Quickstart

### 1. Set up your project

Create a folder and add your system prompt:

```bash
mkdir my-agent
echo "You are a helpful assistant that answers questions clearly and concisely." > my-agent/prompt.txt
```

If you have an existing AI application, copy your actual system prompt into `prompt.txt` instead.

**Don't have evals yet?** Auto-generate them from your prompt:

```bash
evalfix init my-agent/
```

**Have existing tests?** Paste them into your AI IDE (any format — pytest, JSON, CSV, plain text) with this prompt to convert them:

> *Convert these tests into `evals.yaml` for evalfix using this structure:*
>
> ```yaml
> tests:
>   - id: descriptive_test_name
>     input: "the user message to test"
>     expected: "description of what the response should do"
>     grader: semantic        # or: contains, regex, exact
>     expected_output: "..."  # required for contains/regex/exact, omit for semantic
> ```
>
> *Graders: `semantic` — Claude judges whether the output satisfies `expected`. `contains` — checks `expected_output` appears in the response. `exact` — response must match `expected_output` exactly. `regex` — response must match the pattern in `expected_output`.*

Your final project structure:

```
my-agent/
├── prompt.txt      ← your system prompt
├── evals.yaml      ← test cases
└── config.yaml     ← optional: model, temperature, max_tokens
```

`config.yaml` is optional — evalfix defaults to `claude-haiku-4-5-20251001` at `temperature: 1.0`. Create it only if you want to override the model or settings:

```yaml
model: claude-haiku-4-5-20251001
temperature: 1.0
max_tokens: 256
```

---

### 2. Run evals

```bash
evalfix run my-agent/
```

```
Running 8 tests...

 Test                     Result   Score
 basic_greeting           ✓ pass   0.95
 json_only_output         ✗ fail   0.10
 numbered_steps           ✗ fail   0.22

 5 passed  3 failed  avg score 0.61
```

Exits `1` if any tests fail — safe to drop into CI.

---

### 3. Fix failures

```bash
evalfix fix my-agent/
```

evalfix runs a multi-agent loop to diagnose and fix what's broken:
- **Root cause agent** — identifies exactly why the prompt is failing
- **Fix generator** — writes a minimal targeted patch
- **Regression screener** — checks the fix won't break passing tests

```
✓ Fixed in 1 iteration

  - You are a helpful assistant that answers questions clearly and concisely.
  + You are a helpful assistant. When asked for structured output (JSON, haiku,
  + numbered lists), follow the format exactly. Otherwise answer clearly and concisely.

  score  0.61 → 0.91

  Accept this change? [y/N]
```

Type `y` to write the improved prompt back to `prompt.txt`. Use `--yes` to skip the prompt in CI.

---


## Examples

Three ready-to-run projects included in this repo:

| Project | Use case |
|---------|----------|
| `support-classifier/` | Classify support tickets into category + priority JSON |
| `contract-extractor/` | Extract key terms from contract clauses into structured JSON |
| `sales-summarizer/` | Extract deal stage, pain points, and next steps from call transcripts |

```bash
evalfix run support-classifier/
evalfix fix support-classifier/
```

---

## All commands

```bash
evalfix run my-agent/                         # run evals (exits 1 if any fail)
evalfix fix my-agent/                         # fix failures automatically
evalfix fix my-agent/ --yes                   # auto-accept fix (CI)
evalfix run my-agent/ --model claude-opus-4-6 # override model
evalfix run my-agent/ --json                  # output as JSON
evalfix report my-agent/                      # show last run
evalfix report my-agent/ --html               # HTML report
evalfix history my-agent/                     # score trends
evalfix history my-agent/ --html              # HTML chart
evalfix init my-agent/                        # generate evals from prompt.txt
```

---

## CI integration

```yaml
# .github/workflows/eval.yml
- name: Run evals
  run: evalfix run my-agent/
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

---

## Capture production failures with evalfix-sdk

The SDK is how real-world failures become eval cases. Drop it into your production code and every bad response gets automatically picked up by `evalfix fix`.

```bash
pip install evalfix-sdk
```

```python
import time
import evalfix_sdk
from evalfix_sdk import capture

# Point the SDK at your evalfix project directory
evalfix_sdk.configure(queue_file="/path/to/my-agent/.evalfix/failures.jsonl")

response = my_llm_call(user_input)

if quality_score < 0.7:
    capture(
        input=user_input,
        output=response,
        expected="What the response should have said",  # optional
        score=quality_score,                            # optional, 0–1
    )

# Required in scripts — capture() writes on a background thread and needs
# time to flush before the process exits. Not needed in long-running servers.
time.sleep(1)
```

`capture()` never raises and returns immediately — safe to call in any hot path. Failures are written to `.evalfix/failures.jsonl` and automatically ingested the next time you run `evalfix run` or `evalfix fix`:

```bash
evalfix fix my-agent/
# Ingested 3 production failures from evalfix-sdk.
# Running 11 tests...
```

---

## Roadmap

- **Stronger optimization** — more reliable multi-iteration fixing, better root cause diagnosis
- **More graders** — `exact_match`, `json_schema`, custom grader support
- **CI/CD integrations** — GitHub Actions, Slack/email alerts on failure spikes
- **Web dashboard** — team-friendly UI for running evals and tracking trends
- **Agentic support** — eval multi-turn and tool-calling workflows
