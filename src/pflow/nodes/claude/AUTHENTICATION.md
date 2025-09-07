# Claude Code Node Authentication Guide

## Overview

The Claude Code SDK supports **two distinct authentication methods**, each with different billing implications:

1. **API Key Authentication** - Bills to your Anthropic Console account
2. **CLI Authentication** - Uses your Claude Pro/Max subscription entitlements

## Authentication Methods

### Method 1: API Key (Recommended for Production)

Use an Anthropic API key from your Console account:

```bash
# macOS/Linux
export ANTHROPIC_API_KEY=sk-ant-...

# Windows PowerShell
$env:ANTHROPIC_API_KEY="sk-ant-..."

# Windows Command Prompt
set ANTHROPIC_API_KEY=sk-ant-...
```

**Advantages:**
- No CLI installation required
- Works immediately after setting environment variable
- Ideal for CI/CD, Docker, and server deployments
- Standard API usage billing through Console

**Billing:** Usage is charged to your Anthropic Console account at standard API rates.

### Method 2: CLI Authentication (For Development/Personal Use)

Authenticate through the Claude Code CLI:

```bash
# Install CLI first
npm install -g @anthropic-ai/claude-code

# Then authenticate (choose one):
claude auth login      # Interactive OAuth login
claude setup-token     # Long-lived token (requires subscription)
```

**Advantages:**
- Uses your Claude Pro/Max subscription entitlements
- No additional API charges
- Good for personal development

**Billing:** Uses your Claude Pro/Max subscription - no additional API charges.

## How the Node Detects Authentication

The node checks for authentication in this order:

1. **Checks for `ANTHROPIC_API_KEY`** - If found, uses API key authentication
2. **Falls back to CLI authentication** - Requires CLI to be installed and authenticated

```python
# The node automatically detects which method you're using:
if os.getenv("ANTHROPIC_API_KEY"):
    # Uses API key authentication
else:
    # Uses CLI authentication (requires CLI installed)
```

## Usage in Workflows

Both authentication methods work identically in workflows:

```json
{
  "nodes": [
    {
      "id": "claude",
      "type": "claude-code",
      "params": {
        "task": "Write a function to parse JSON",
        "working_directory": "./src"
      }
    }
  ]
}
```

## Environment Variables

### ANTHROPIC_API_KEY
Your Anthropic API key for Console billing:
```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
```

### CLAUDE_CODE_PATH
Custom path to Claude CLI executable (optional):
```bash
export CLAUDE_CODE_PATH="/custom/path/to/claude"
```

## Platform Support

The SDK also supports alternative AI platforms through environment variables:

### AWS Bedrock
```bash
export ANTHROPIC_BEDROCK_REGION=us-east-1
export ANTHROPIC_BEDROCK_AUTH=profile  # or 'keys'
# Additional AWS credentials as needed
```

### Google Vertex AI
```bash
export ANTHROPIC_VERTEX_REGION=us-central1
export ANTHROPIC_VERTEX_PROJECT_ID=your-project
# Additional Google Cloud credentials as needed
```

## Common Scenarios

### CI/CD Pipeline
Use API key authentication for automated workflows:
```yaml
env:
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### Docker Container
```dockerfile
ENV ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
```

### Local Development
Choose based on your billing preference:
- API key if you want to bill to Console
- CLI auth if you have Claude Pro/Max subscription

### Team Development
- Each developer can use their preferred authentication method
- API keys can be shared (with caution) or individual
- CLI auth is always individual

## Troubleshooting

### "Claude Code CLI not installed"
**Solution:** Either:
1. Set `ANTHROPIC_API_KEY` environment variable, OR
2. Install the CLI: `npm install -g @anthropic-ai/claude-code`

### "Not authenticated with Claude Code"
**Solution:** Either:
1. Set `ANTHROPIC_API_KEY` environment variable, OR
2. Run `claude auth login` to authenticate via CLI

### "Rate limit exceeded"
- **API Key:** Check your Console usage limits
- **CLI Auth:** Check your subscription tier limits

## Security Best Practices

1. **Never commit API keys** to version control
2. **Use environment variables** or secret management systems
3. **Rotate API keys** regularly
4. **Use separate keys** for development and production
5. **Set appropriate rate limits** in Console

## Billing Comparison

| Method | Billing | Best For |
|--------|---------|----------|
| API Key | Anthropic Console (pay per token) | Production, CI/CD, team projects |
| CLI Auth | Claude Pro/Max subscription | Personal use, development, testing |

## Skip Authentication Check

For testing or when you know authentication is configured:

```json
{
  "params": {
    "skip_auth_check": true
  }
}
```

## Summary

The Claude Code node provides flexible authentication to suit different use cases:
- **Production/CI/CD**: Use API keys for predictable billing
- **Development**: Use CLI auth with your subscription
- **Both methods** work seamlessly with the same code

The node automatically detects which authentication method you're using based on environment variables, making it easy to switch between them as needed.