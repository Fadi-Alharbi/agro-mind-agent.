import pytest

from db.customer_state import GROUP_BUY_MIN_QUANTITY, _validate_group_buy_quantity


def test_group_buy_rejects_quantity_below_minimum():
    with pytest.raises(ValueError, match=f"at least {GROUP_BUY_MIN_QUANTITY}"):
        _validate_group_buy_quantity(GROUP_BUY_MIN_QUANTITY - 1)


def test_group_buy_accepts_minimum_quantity():
    _validate_group_buy_quantity(GROUP_BUY_MIN_QUANTITY)
