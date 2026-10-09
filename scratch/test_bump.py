from decimal import Decimal

def test_bump(v):
    return str(Decimal(v) + Decimal('0.01'))

assert test_bump('1.00') == '1.01'
assert test_bump('1.09') == '1.10'
assert test_bump('1.99') == '2.00'
assert test_bump('2.99') == '3.00'
print("Bump arithmetic tests pass.")
