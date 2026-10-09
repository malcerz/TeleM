with open('src/gui/qt/tabs/load_tab.py', 'r', encoding='utf-8') as f:
    text = f.read()
if 'import time' not in text:
    text = "import time\n" + text
with open('src/gui/qt/tabs/load_tab.py', 'w', encoding='utf-8') as f:
    f.write(text)
