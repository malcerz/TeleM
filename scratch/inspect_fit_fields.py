import fitparse

fitfile = fitparse.FitFile("Video/Jazda_na_rowerze_w_porze_lunchu.fit")
print("Reading record messages...")

dev_fields = []
all_field_names = {}

for msg in fitfile.get_messages("record"):
    for field in msg:
        name = field.name
        # Check attributes of field
        all_field_names[name] = type(field)
        # Check if field is developer field
        if hasattr(field, "field_def"):
            fd = field.field_def
            # fd has def_num, dev_data_index, etc.
            is_dev = getattr(fd, "is_dev", False) if hasattr(fd, "is_dev") else False
            dev_idx = getattr(fd, "developer_data_index", None)
            field_num = getattr(fd, "field_def_num", None) or getattr(fd, "def_num", None)
            if dev_idx is not None or is_dev:
                dev_fields.append((name, dev_idx, field_num, dir(field), dir(fd)))
    if len(dev_fields) > 20:
        break

print("All field names count:", len(all_field_names))
print("Sample dev fields:")
for df in dev_fields[:10]:
    print(df[0], "dev_idx=", df[1], "field_num=", df[2])

# Let's inspect fields in a single record message in full detail
for msg in fitfile.get_messages("record"):
    print("\n--- Record Message Fields ---")
    for f in msg.fields:
        print(f"Native field: name='{f.name}', def_num={getattr(f, 'def_num', None)}, val={f.value}, units={getattr(f, 'units', None)}")
    if hasattr(msg, "developer_fields"):
        for df in msg.developer_fields:
            fd = getattr(df, "field_def", None)
            dev_idx = getattr(fd, "developer_data_index", None) if fd else None
            f_num = getattr(fd, "field_def_num", None) if fd else None
            print(f"Developer field: name='{df.name}', dev_idx={dev_idx}, f_num={f_num}, val={df.value}, units={getattr(df, 'units', None)}")
    break
