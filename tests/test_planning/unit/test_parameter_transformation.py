"""Test parameter value transformation in ParameterDiscoveryNode."""

from pflow.planning.nodes import ParameterDiscoveryNode


class TestParameterTransformation:
    """Test the _templatize_user_input method."""

    def test_basic_replacement(self):
        """Test basic parameter value replacement."""
        node = ParameterDiscoveryNode()

        user_input = "generate changelog from last 30 closed issues in pflow repo"
        extracted_params = {"issue_count": 30, "repo_name": "pflow"}

        result = node._templatize_user_input(user_input, extracted_params)

        assert result == "generate changelog from last ${issue_count} closed issues in ${repo_name} repo"

    def test_multiple_occurrences(self):
        """Test replacing multiple occurrences of the same value."""
        node = ParameterDiscoveryNode()

        user_input = "copy files from /home/user to /home/user/backup"
        extracted_params = {"source_path": "/home/user", "dest_path": "/home/user/backup"}

        result = node._templatize_user_input(user_input, extracted_params)

        # Should replace longer value first to avoid partial replacements
        assert result == "copy files from ${source_path} to ${dest_path}"

    def test_no_parameters(self):
        """Test with empty parameters returns original input."""
        node = ParameterDiscoveryNode()

        user_input = "do something generic"
        extracted_params = {}

        result = node._templatize_user_input(user_input, extracted_params)

        assert result == "do something generic"

    def test_overlapping_values(self):
        """Test handling of overlapping parameter values."""
        node = ParameterDiscoveryNode()

        user_input = "process 2024 records from year 2024"
        extracted_params = {"count": 2024, "year": 2024}

        result = node._templatize_user_input(user_input, extracted_params)

        # Both occurrences should be replaced
        assert "${count}" in result or "${year}" in result
        # Should not contain the original value
        assert "2024" not in result

    def test_none_values(self):
        """Test that None values are skipped."""
        node = ParameterDiscoveryNode()

        user_input = "fetch data from API"
        extracted_params = {"api_key": None, "endpoint": "data"}

        result = node._templatize_user_input(user_input, extracted_params)

        # Should only replace non-None values
        assert result == "fetch ${endpoint} from API"

    def test_integer_and_string_values(self):
        """Test with mixed integer and string parameter values."""
        node = ParameterDiscoveryNode()

        user_input = "analyze 100 entries from database prod_db"
        extracted_params = {"count": 100, "database": "prod_db"}

        result = node._templatize_user_input(user_input, extracted_params)

        assert result == "analyze ${count} entries from database ${database}"

    def test_partial_match_avoidance(self):
        """Test that longer values are replaced first to avoid partial matches."""
        node = ParameterDiscoveryNode()

        user_input = "backup /var/log and /var/log/apache2"
        extracted_params = {"base_dir": "/var/log", "apache_dir": "/var/log/apache2"}

        result = node._templatize_user_input(user_input, extracted_params)

        # Longer path should be replaced first
        assert result == "backup ${base_dir} and ${apache_dir}"

    def test_case_sensitive_replacement(self):
        """Test that replacements are case-sensitive."""
        node = ParameterDiscoveryNode()

        user_input = "Process data from DATA_SOURCE"
        extracted_params = {"source": "data"}

        result = node._templatize_user_input(user_input, extracted_params)

        # Should not replace "DATA" as it's different case
        assert result == "Process ${source} from DATA_SOURCE"

    def test_special_characters_in_values(self):
        """Test handling of special characters in parameter values."""
        node = ParameterDiscoveryNode()

        user_input = "connect to user@host.com:8080"
        extracted_params = {"connection": "user@host.com:8080"}

        result = node._templatize_user_input(user_input, extracted_params)

        assert result == "connect to ${connection}"

    def test_empty_string_value(self):
        """Test that empty string values are handled correctly."""
        node = ParameterDiscoveryNode()

        user_input = "process file with default options"
        extracted_params = {"options": ""}

        result = node._templatize_user_input(user_input, extracted_params)

        # Empty string shouldn't cause issues but also won't match anything
        assert result == "process file with default options"
