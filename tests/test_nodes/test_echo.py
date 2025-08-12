"""Tests for the echo node."""

from pflow.nodes.test.echo import EchoNode


def test_echo_basic():
    """Test basic echo functionality."""
    node = EchoNode()
    shared = {"message": "Hello"}

    prep_res = node.prep(shared)
    exec_res = node.exec(prep_res)
    action = node.post(shared, prep_res, exec_res)

    assert shared["echo"] == "Hello"
    assert shared["metadata"]["original_message"] == "Hello"
    assert shared["metadata"]["count"] == 1
    assert shared["metadata"]["modified"] is False
    assert action == "default"


def test_echo_with_count():
    """Test echo with repetition."""
    node = EchoNode()
    shared = {"message": "Hi", "count": 3}

    prep_res = node.prep(shared)
    exec_res = node.exec(prep_res)
    node.post(shared, prep_res, exec_res)

    assert shared["echo"] == "Hi Hi Hi"
    assert shared["metadata"]["count"] == 3
    assert shared["metadata"]["modified"] is True


def test_echo_with_prefix_suffix():
    """Test echo with prefix and suffix."""
    node = EchoNode()
    node.params = {"prefix": "[", "suffix": "]"}
    shared = {"message": "Test"}

    prep_res = node.prep(shared)
    exec_res = node.exec(prep_res)
    node.post(shared, prep_res, exec_res)

    assert shared["echo"] == "[Test]"
    assert shared["metadata"]["modified"] is True


def test_echo_uppercase():
    """Test echo with uppercase transformation."""
    node = EchoNode()
    node.params = {"uppercase": True}
    shared = {"message": "hello world"}

    prep_res = node.prep(shared)
    exec_res = node.exec(prep_res)
    node.post(shared, prep_res, exec_res)

    assert shared["echo"] == "HELLO WORLD"
    assert shared["metadata"]["modified"] is True


def test_echo_pass_through_data():
    """Test echo passes through arbitrary data."""
    node = EchoNode()
    test_data = {"key": "value", "number": 42}
    shared = {"message": "Test", "data": test_data}

    prep_res = node.prep(shared)
    exec_res = node.exec(prep_res)
    node.post(shared, prep_res, exec_res)

    assert shared["data"] == test_data
    assert shared["echo"] == "Test"


def test_echo_default_message():
    """Test echo uses default message when none provided."""
    node = EchoNode()
    shared = {}

    prep_res = node.prep(shared)
    exec_res = node.exec(prep_res)
    node.post(shared, prep_res, exec_res)

    assert shared["echo"] == "Hello, World!"
    assert shared["metadata"]["original_message"] == "Hello, World!"


def test_echo_combined_transformations():
    """Test echo with multiple transformations."""
    node = EchoNode()
    node.params = {"prefix": ">>> ", "suffix": " <<<", "uppercase": True}
    shared = {"message": "test", "count": 2}

    prep_res = node.prep(shared)
    exec_res = node.exec(prep_res)
    node.post(shared, prep_res, exec_res)

    assert shared["echo"] == ">>> TEST <<< >>> TEST <<<"
    assert shared["metadata"]["modified"] is True
    assert shared["metadata"]["count"] == 2
