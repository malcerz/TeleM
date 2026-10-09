with open('src/telemetry_native_gpmf.py', 'r') as f:
    text = f.read()

old_vector_array = '''    def vector_array(samples: list) -> np.ndarray:
        if not samples:
            return np.zeros((0, 4), dtype=np.float64)
        return np.asarray(
            [[float(ts), float(vec[0]), float(vec[1]), float(vec[2])] for ts, vec in samples],
            dtype=np.float64,
        )'''

new_vector_array = '''    def vector_array(samples: list) -> np.ndarray:
        if not samples:
            return np.zeros((0, 4), dtype=np.float64)
        # Fast flattening with generator, then fromiter, then reshape
        def _flatten():
            for ts, vec in samples:
                yield float(ts)
                yield float(vec[0])
                yield float(vec[1])
                yield float(vec[2])
        return np.fromiter(_flatten(), dtype=np.float64).reshape(-1, 4)'''

if old_vector_array in text:
    text = text.replace(old_vector_array, new_vector_array)
    with open('src/telemetry_native_gpmf.py', 'w') as f:
        f.write(text)
    print('np.fromiter optimization restored')
else:
    print('Failed to find vector_array')
