with open('scripts/test_amd_real.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('window.load_tab', 'window._load_tab')
text = text.replace('window.render_tab', 'window._render_tab')
text = text.replace('window.settings_tab', 'window._settings_tab')
text = text.replace('window.project_ready', 'window._controller._project_manager.is_project_ready() if hasattr(window, "_controller") else False')

# To set range
text = text.replace('vt = window._video_timeline', 'vt = window._controller._project_manager._video_timeline')

with open('scripts/test_amd_real.py', 'w', encoding='utf-8') as f:
    f.write(text)
