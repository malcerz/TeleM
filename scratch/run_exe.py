import subprocess
res = subprocess.run(["scratch/microbench_fused_candidates.exe"], capture_output=True, text=True)
print("STDOUT:", res.stdout)
print("STDERR:", res.stderr)
print("RETURNCODE:", res.returncode)
