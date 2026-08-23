import fitparse

fitfile = fitparse.FitFile("Video/Jazda_na_rowerze_w_porze_lunchu.fit")

# 1. Map developer field definitions: (dev_data_index, def_num) -> {name, units, etc.}
dev_field_defs = {}
for msg in fitfile.get_messages("field_description"):
    vals = {f.name: f.value for f in msg.fields}
    dev_idx = vals.get("developer_data_index")
    f_num = vals.get("field_definition_number")
    fname = vals.get("field_name")
    funits = vals.get("units")
    if dev_idx is not None and f_num is not None:
        dev_field_defs[(dev_idx, f_num)] = {
            "name": str(fname) if fname else f"dev_{dev_idx}_{f_num}",
            "units": str(funits) if funits else "",
            "dev_idx": dev_idx,
            "f_num": f_num,
        }

print("Discovered Developer Field Descriptions in FIT:")
for k, v in sorted(dev_field_defs.items()):
    print(f"  Dev {k[0]}:{k[1]} -> name='{v['name']}', units='{v['units']}'")

# 2. Inspect record messages and how fields are extracted
record_field_counts = {}
for msg in fitfile.get_messages("record"):
    for f in msg.fields:
        fd = getattr(f, "field_def", None)
        is_dev = isinstance(fd, fitparse.records.DevFieldDefinition)
        dev_idx = getattr(fd, "dev_data_index", None) if is_dev else None
        def_num = getattr(fd, "def_num", None) if is_dev else getattr(f, "def_num", None)
        raw_name = f.name
        key = (raw_name, is_dev, dev_idx, def_num)
        if key not in record_field_counts:
            record_field_counts[key] = {"count": 0, "non_null": 0, "units": f.units}
        record_field_counts[key]["count"] += 1
        if f.value is not None:
            record_field_counts[key]["non_null"] += 1

print("\nDiscovered Record Fields in FIT:")
for (raw_name, is_dev, dev_idx, def_num), st in sorted(record_field_counts.items(), key=lambda x: (x[0][1], str(x[0][0]), str(x[0][2]))):
    kind = f"DEV [{dev_idx}:{def_num}]" if is_dev else f"NATIVE [{def_num}]"
    print(f"  {raw_name:25} {kind:16} non_null={st['non_null']:5} / {st['count']:5} units='{st['units']}'")
