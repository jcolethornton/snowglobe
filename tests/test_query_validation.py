import pytest
from snowglobe.collectors.query_profile import _validate_query_id


class TestQueryIdValidation:
    def test_valid_uuid_accepted(self):
        result = _validate_query_id("01bd3a9d-0910-8327-0000-09717704c032")
        assert result == "01bd3a9d-0910-8327-0000-09717704c032"

    def test_uppercase_uuid_accepted(self):
        result = _validate_query_id("01BD3A9D-0910-8327-0000-09717704C032")
        assert result == "01BD3A9D-0910-8327-0000-09717704C032"

    def test_sql_injection_rejected(self):
        with pytest.raises(ValueError, match="Invalid query ID"):
            _validate_query_id("'; DROP TABLE users; --")

    def test_empty_string_rejected(self):
        with pytest.raises(ValueError, match="Invalid query ID"):
            _validate_query_id("")

    def test_partial_uuid_rejected(self):
        with pytest.raises(ValueError, match="Invalid query ID"):
            _validate_query_id("01bd3a9d-0910")

    def test_uuid_with_extra_chars_rejected(self):
        with pytest.raises(ValueError, match="Invalid query ID"):
            _validate_query_id("01bd3a9d-0910-8327-0000-09717704c032; DROP")

    def test_non_hex_chars_rejected(self):
        with pytest.raises(ValueError, match="Invalid query ID"):
            _validate_query_id("01bd3a9d-0910-8327-0000-0971770XYZAB")
