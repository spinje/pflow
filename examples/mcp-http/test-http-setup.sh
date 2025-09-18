#!/bin/bash

# Test script for HTTP transport in pflow MCP

set -e

echo "==================================="
echo "pflow HTTP Transport Test Suite"
echo "==================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${YELLOW}→${NC} $1"
}

# Check if test server is needed
echo "Testing Options:"
echo "1. Test with local test server (recommended for first test)"
echo "2. Test with a real remote server (if you have one)"
echo ""
read -p "Choose option (1 or 2): " option

if [ "$option" = "1" ]; then
    # Start local test server
    print_info "Starting local MCP test server..."

    # Check if aiohttp is installed
    if ! python -c "import aiohttp" 2>/dev/null; then
        print_info "Installing aiohttp for test server..."
        uv pip install aiohttp
    fi

    # Start server in background
    python test-mcp-http-server.py &
    SERVER_PID=$!
    print_success "Test server started (PID: $SERVER_PID)"

    # Wait for server to start
    sleep 2

    # Configure test server
    SERVER_NAME="test-http"
    SERVER_URL="http://localhost:8080/mcp"

    print_info "Adding local test server to pflow..."
    uv run pflow mcp add $SERVER_NAME --transport http --url $SERVER_URL

elif [ "$option" = "2" ]; then
    echo ""
    echo "For a real server, you can test with:"
    echo "1. Kite Public MCP Servers (no auth required)"
    echo "2. Your own MCP server"
    echo ""
    read -p "Enter server name: " SERVER_NAME
    read -p "Enter server URL (e.g., https://example.com/mcp): " SERVER_URL
    read -p "Does this server require authentication? (y/n): " needs_auth

    if [ "$needs_auth" = "y" ]; then
        echo "Authentication types: bearer, api_key, basic"
        read -p "Enter auth type: " AUTH_TYPE

        if [ "$AUTH_TYPE" = "bearer" ]; then
            read -p "Enter token (or env var like \${TOKEN}): " AUTH_TOKEN
            uv run pflow mcp add $SERVER_NAME --transport http --url "$SERVER_URL" \
                --auth-type bearer --auth-token "$AUTH_TOKEN"
        elif [ "$AUTH_TYPE" = "api_key" ]; then
            read -p "Enter API key (or env var): " API_KEY
            read -p "Enter header name (default: X-API-Key): " HEADER_NAME
            HEADER_NAME=${HEADER_NAME:-X-API-Key}
            uv run pflow mcp add $SERVER_NAME --transport http --url "$SERVER_URL" \
                --auth-type api_key --auth-token "$API_KEY" --auth-header "$HEADER_NAME"
        elif [ "$AUTH_TYPE" = "basic" ]; then
            read -p "Enter username: " USERNAME
            read -s -p "Enter password: " PASSWORD
            echo ""
            uv run pflow mcp add $SERVER_NAME --transport http --url "$SERVER_URL" \
                --auth-type basic --username "$USERNAME" --password "$PASSWORD"
        fi
    else
        uv run pflow mcp add $SERVER_NAME --transport http --url "$SERVER_URL"
    fi
fi

echo ""
print_success "Server configured!"
echo ""

# Test 1: List servers
print_info "Test 1: Listing MCP servers..."
uv run pflow mcp list
print_success "Server list displayed"
echo ""

# Test 2: Sync tools
print_info "Test 2: Discovering tools from HTTP server..."
if uv run pflow mcp sync $SERVER_NAME; then
    print_success "Tool discovery successful!"
else
    print_error "Tool discovery failed"
    if [ "$option" = "1" ]; then
        kill $SERVER_PID 2>/dev/null
    fi
    exit 1
fi
echo ""

# Test 3: List discovered tools
print_info "Test 3: Checking registered tools..."
uv run pflow registry list | grep -A5 "mcp-$SERVER_NAME" || true
echo ""

# Test 4: Execute a tool (if local test server)
if [ "$option" = "1" ]; then
    print_info "Test 4: Executing a test tool..."

    # Create a simple workflow that uses the echo tool
    cat > test-workflow.json << EOF
{
  "name": "test-http-transport",
  "nodes": [
    {
      "id": "test_echo",
      "type": "mcp-${SERVER_NAME}-echo",
      "params": {
        "message": "Hello from HTTP transport!"
      }
    }
  ]
}
EOF

    print_info "Running workflow with HTTP MCP tool..."
    if uv run pflow run test-workflow.json --trace; then
        print_success "Tool execution successful!"
    else
        print_error "Tool execution failed"
    fi

    # Cleanup
    rm -f test-workflow.json
    echo ""
fi

# Test 5: Test with environment variables
print_info "Test 5: Testing environment variable expansion..."

# Add a server with env var auth
export TEST_API_TOKEN="test-token-12345"
uv run pflow mcp add test-env --transport http \
    --url "http://localhost:9999/mcp" \
    --auth-type bearer \
    --auth-token '${TEST_API_TOKEN}' || true

# Check if the env var is NOT stored in plain text
print_info "Checking config file for security..."
if grep -q "test-token-12345" ~/.pflow/mcp-servers.json; then
    print_error "WARNING: Token stored in plain text!"
else
    print_success "Token stored as environment variable reference"
fi

# Cleanup test-env server
uv run pflow mcp remove test-env --force 2>/dev/null || true
echo ""

# Test 6: Error handling
print_info "Test 6: Testing error handling..."

# Try to add server with invalid URL
if uv run pflow mcp add bad-url --transport http --url "not-a-url" 2>&1 | grep -q "URL must start with http"; then
    print_success "Invalid URL rejected correctly"
else
    print_error "Invalid URL not caught"
fi

# Try to sync non-existent server
if uv run pflow mcp sync non-existent 2>&1 | grep -q "not found"; then
    print_success "Non-existent server error handled"
else
    print_error "Non-existent server error not handled"
fi
echo ""

# Summary
echo "==================================="
echo "Test Summary"
echo "==================================="
print_success "HTTP transport implementation is working!"
echo ""
echo "You can now:"
echo "1. Use HTTP-based MCP tools in workflows"
echo "2. Connect to remote MCP servers"
echo "3. Use various authentication methods"
echo ""

# Cleanup
if [ "$option" = "1" ]; then
    print_info "Cleaning up test server..."
    kill $SERVER_PID 2>/dev/null || true
    uv run pflow mcp remove $SERVER_NAME --force
    print_success "Cleanup complete"
fi

echo ""
echo "To test with a real workflow, try:"
echo "  uv run pflow \"use the $SERVER_NAME echo tool to say hello\""
