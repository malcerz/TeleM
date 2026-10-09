with open('src/gui/qt/tabs/load_tab.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.strip() == 'import os':
        new_lines.append(line)
        new_lines.append('import time\n')
    else:
        new_lines.append(line)

with open('src/gui/qt/tabs/load_tab.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
