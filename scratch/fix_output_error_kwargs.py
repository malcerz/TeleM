with open('src/ffmpeg/output_error.py', 'r', encoding='utf-8') as f:
    text = f.read()

old_init = '''        elif "broken pipe" in os_error:
            self.category = ExportOutputCategory.BROKEN_PIPE
            code = "EPIPE"
        else:
            self.category = ExportOutputCategory.UNKNOWN
            code = "STORAGE_ERROR"
        
        kwargs.pop("output_path", None)
        kwargs.pop("os_error", None)
        super().__init__(user_message=message, code=code, **kwargs)'''

new_init = '''        elif "broken pipe" in os_error:
            cat = ExportOutputCategory.BROKEN_PIPE
            code = "EPIPE"
        else:
            cat = ExportOutputCategory.UNKNOWN
            code = "STORAGE_ERROR"
        
        kwargs.pop("output_path", None)
        kwargs.pop("os_error", None)
        super().__init__(user_message=message, code=code, **kwargs)
        self.category = cat'''

text = text.replace(old_init, new_init)
text = text.replace('self.category = ExportOutputCategory.DISK_FULL', 'cat = ExportOutputCategory.DISK_FULL')
text = text.replace('self.category = ExportOutputCategory.PERMISSION_DENIED', 'cat = ExportOutputCategory.PERMISSION_DENIED')
text = text.replace('self.category = ExportOutputCategory.DEVICE_UNAVAILABLE', 'cat = ExportOutputCategory.DEVICE_UNAVAILABLE')

with open('src/ffmpeg/output_error.py', 'w', encoding='utf-8') as f:
    f.write(text)
