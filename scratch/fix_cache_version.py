with open('src/telemetry_cache_manager.py', 'r') as f:
    text = f.read()

text = text.replace('CACHE_FORMAT_VERSION = 1', 'CACHE_FORMAT_VERSION = 2')
with open('src/telemetry_cache_manager.py', 'w') as f:
    f.write(text)
