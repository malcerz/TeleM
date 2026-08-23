import fitparse

fitfile = fitparse.FitFile("Video/Jazda_na_rowerze_w_porze_lunchu.fit")

for msg in fitfile.get_messages("record"):
    for f in msg.fields:
        fd = getattr(f, "field_def", None)
        if isinstance(fd, fitparse.records.DevFieldDefinition):
            print(f"Dev field: name='{f.name}', def_num={fd.def_num}, dev_data_index={fd.dev_data_index}, units={f.units}")
    break

# Also check field definitions in other messages (e.g. field_description messages)
print("\n--- Field Description Messages ---")
for msg in fitfile.get_messages("field_description"):
    d = {f.name: f.value for f in msg.fields}
    print(f"field_description: dev_data_index={d.get('developer_data_index')}, field_def_num={d.get('field_definition_number')}, field_name={d.get('field_name')}, units={d.get('units')}")
