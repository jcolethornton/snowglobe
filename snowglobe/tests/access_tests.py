from snowglobe.models.privilege import Privilege


def test_ownership_allows_select():
    assert Privilege.matches(Privilege.OWNERSHIP, Privilege.SELECT)
