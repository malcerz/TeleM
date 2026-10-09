import re
import os
import sys

def bump_version():
    version_file = os.path.join(os.path.dirname(__file__), '..', 'src', 'version.py')
    with open(version_file, 'r', encoding='utf-8') as f:
        text = f.read()

    match = re.search(r"APP_VERSION\s*=\s*['\"](\d+\.\d+)['\"]", text)
    if not match:
        print("Could not find APP_VERSION in src/version.py")
        sys.exit(1)

    old_version_str = match.group(1)
    old_version_float = float(old_version_str)
    new_version_float = old_version_float + 0.01
    new_version_str = f"{new_version_float:.2f}"

    text = text.replace(f"'{old_version_str}'", f"'{new_version_str}'")
    text = text.replace(f'"{old_version_str}"', f'"{new_version_str}"')

    with open(version_file, 'w', encoding='utf-8') as f:
        f.write(text)

    print(f"Bumped version from {old_version_str} to {new_version_str}")
    return new_version_str

if __name__ == '__main__':
    bump_version()
