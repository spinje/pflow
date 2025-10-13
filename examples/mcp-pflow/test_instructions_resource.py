#!/usr/bin/env python3
"""Test that the instructions resource is accessible via MCP protocol.

This script starts the pflow MCP server and verifies:
1. Server starts successfully
2. Resources can be listed
3. pflow://instructions resource exists
4. Resource content can be read
"""

import asyncio
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_instructions_resource():
    """Test reading the instructions resource via MCP."""
    print("🔍 Starting pflow MCP server...")

    # Get project root (2 levels up from this file)
    project_root = Path(__file__).parent.parent.parent

    # Server parameters
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "pflow", "mcp", "serve"],
        cwd=str(project_root),
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                print("✓ Connected to server")

                # Initialize
                await session.initialize()
                print("✓ Initialized session")

                # List resources
                print("\n📚 Listing resources...")
                resources = await session.list_resources()
                print(f"✓ Found {len(resources.resources)} resource(s)")

                for resource in resources.resources:
                    print(f"  - {resource.uri}")
                    if resource.name:
                        print(f"    Name: {resource.name}")
                    if resource.description:
                        print(f"    Description: {resource.description[:100]}...")

                # Check if instructions resource exists
                instructions_uri = "pflow://instructions"
                instructions_resource = next(
                    (r for r in resources.resources if str(r.uri) == instructions_uri),
                    None
                )

                if not instructions_resource:
                    print(f"\n❌ FAIL: {instructions_uri} not found in resources")
                    return False

                print(f"\n✓ Found {instructions_uri} resource")

                # Read the resource
                print(f"\n📖 Reading {instructions_uri}...")
                result = await session.read_resource(instructions_uri)

                if not result.contents:
                    print("❌ FAIL: No content returned")
                    return False

                content = result.contents[0]
                text = content.text if hasattr(content, 'text') else str(content)

                print(f"✓ Received {len(text)} bytes")
                print(f"\nFirst 200 characters:")
                print("-" * 60)
                print(text[:200])
                print("-" * 60)

                # Verify content looks like agent instructions
                expected_keywords = ["pflow", "workflow", "agent", "discover"]
                found_keywords = [kw for kw in expected_keywords if kw.lower() in text.lower()]

                print(f"\n✓ Found {len(found_keywords)}/{len(expected_keywords)} expected keywords: {found_keywords}")

                if len(found_keywords) < len(expected_keywords) - 1:
                    print("⚠️  WARNING: Content may not be agent instructions")
                    return False

                print("\n✅ SUCCESS: Instructions resource is working correctly!")
                return True

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_instructions_resource())
    sys.exit(0 if success else 1)
