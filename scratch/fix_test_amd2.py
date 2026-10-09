with open('scripts/test_amd_real.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('window._render_tab.edit_duration.setText("5")', '# window._render_tab.edit_duration.setText("5")')

with open('scripts/test_amd_real.py', 'w', encoding='utf-8') as f:
    f.write(text)
