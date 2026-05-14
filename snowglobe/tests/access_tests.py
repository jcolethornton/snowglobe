from snowglobe.models.enums import Privilege

def test_ownership_allows_select():
    assert privilege_matches(Privilege.OWNERSHIP, Privilege.SELECT)
