import fitparse

fitfile = fitparse.FitFile("Video/Jazda_na_rowerze_w_porze_lunchu.fit")

for msg in fitfile.get_messages("record"):
    for f in msg.fields:
        fd = getattr(f, "field_def", None)
        # inspect fd attributes
        if f.name in ("battery_pct", "solar_pct", "solar", "curVpower", "battery", "temperature", "discharge", "K1", "K2"):
            dev_data_idx = getattr(fd, "developer_data_index", None)
            def_num = getattr(f, "def_num", None)
            fd_def_num = getattr(fd, "field_def_num", None)
            parent = getattr(fd, "parent", None)
            print(f"Field: name={f.name:15} def_num={def_num} fd_def_num={fd_def_num} dev_data_idx={dev_data_idx} fd={type(fd).__name__} attrs={[a for a in dir(fd) if not a.startswith('_')]}")
    break
