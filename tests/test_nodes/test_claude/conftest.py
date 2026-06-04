"""Install the mock ``claude_agent_sdk`` before any test module in this directory
imports ``pflow.nodes.claude.claude_code``.

pytest imports a directory's ``conftest.py`` before collecting (importing) the test
modules in that directory, so calling ``install()`` here guarantees the mock SDK is in
``sys.modules`` before the node binds its SDK names — independent of which test file
pytest imports first. (Previously the injection lived at module scope in
``test_claude_code.py`` and broke when ``test_schema_coercion.py`` imported the node
first, binding it to the real SDK.) See tests/CLAUDE.md #17.
"""

from tests.shared.claude_sdk_stub import install

install()
