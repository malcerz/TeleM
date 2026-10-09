with open('tests/test_output_write_error.py', 'r', encoding='utf-8') as f:
    text = f.read()
text = text.replace('assert err.code == "EACCES"', 'assert err.code == "PERMISSION_DENIED"')
with open('tests/test_output_write_error.py', 'w', encoding='utf-8') as f:
    f.write(text)
