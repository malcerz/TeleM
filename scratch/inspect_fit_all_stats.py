import fitparse

fitfile = fitparse.FitFile("Video/Jazda_na_rowerze_w_porze_lunchu.fit")

field_stats = {}

for msg in fitfile.get_messages("record"):
    for f in msg.fields:
        name = f.name
        fd = getattr(f, "field_def", None)
        dev_idx = getattr(fd, "developer_data_index", None) if fd else None
        f_num = getattr(f, "def_num", None)
        is_dev = getattr(f, "is_dev", None)
        key = (name, f_num, dev_idx, type(f).__name__)
        if key not in field_stats:
            field_stats[key] = {
                "count": 0, "non_null": 0, "min": None, "max": None, "units": getattr(f, "units", None)
            }
        field_stats[key]["count"] += 1
        if f.value is not None:
            field_stats[key]["non_null"] += 1
            if isinstance(f.value, (int, float)):
                v = float(f.value)
                if field_stats[key]["min"] is None or v < field_stats[key]["min"]:
                    field_stats[key]["min"] = v
                if field_stats[key]["max"] is None or v > field_stats[key]["max"]:
                    field_stats[key]["max"] = v

print(f"{'Name':25} {'def_num':8} {'dev_idx':8} {'Type':18} {'non_null':10} {'Min':10} {'Max':10} {'Units'}")
print("-" * 105)
for (name, f_num, dev_idx, f_type), stats in sorted(field_stats.items(), key=lambda x: str(x[0][0])):
    print(f"{name:25} {str(f_num):8} {str(dev_idx):8} {f_type:18} {stats['non_null']:10} {str(stats['min']):10} {str(stats['max']):10} {str(stats['units'])}")
