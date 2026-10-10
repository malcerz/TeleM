import re
import os
import sys
from decimal import Decimal

def next_version(version: str) -> str:
    fractional_digits = len(version.partition(".")[2])
    if fractional_digits < 1 or not version.partition(".")[0].isdigit() or not version.partition(".")[2].isdigit():
        raise ValueError(f"Invalid decimal version: {version}")
    current = Decimal(version)
    increment = Decimal(1).scaleb(-fractional_digits)
    return f"{current + increment:.{fractional_digits}f}"


def bump_version():
    version_file = os.path.join(os.path.dirname(__file__), '..', 'src', 'version.py')
    with open(version_file, 'r', encoding='utf-8') as f:
        text = f.read()

    match = re.search(r"(?m)^APP_VERSION\s*=\s*(['\"])(\d+\.\d+)\1\s*$", text)
    if not match:
        print("Could not find APP_VERSION in src/version.py")
        sys.exit(1)

    quote, old_version_str = match.group(1), match.group(2)
    new_version_str = next_version(old_version_str)

    text = text[:match.start()] + (
        f"APP_VERSION = {quote}{new_version_str}{quote}"
    ) + text[match.end():]

    with open(version_file, 'w', encoding='utf-8') as f:
        f.write(text)

    print(f"Bumped version from {old_version_str} to {new_version_str}")
    return new_version_str

if __name__ == '__main__':
    bump_version()
