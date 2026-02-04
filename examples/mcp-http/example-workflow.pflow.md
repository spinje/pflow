# MCP HTTP Transport Test

Test MCP tools served over HTTP transport with echo, time, and math operations.

## Steps

### echo_test

Test the HTTP echo tool by sending a message.

- type: mcp-test-http-echo
- message: HTTP transport is amazing!

### time_test

Test the HTTP time tool to get the current time.

- type: mcp-test-http-get_time

### math_test

Test the HTTP math tool to add two numbers.

- type: mcp-test-http-add_numbers
- a: 10
- b: 32
