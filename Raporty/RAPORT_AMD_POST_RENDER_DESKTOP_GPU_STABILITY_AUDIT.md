# RAPORT — AMD post-render desktop / GPU stability audit

## TASK

Investigate the potential for `explorer.exe` or the GPU driver to appear to
hang after an AMD render finishes.  This stage is diagnostic only: no renderer,
driver, page-file, registry, or operating-system settings were changed.

## INITIAL STATE

- Branch: `integration/intel-amd`
- HEAD: `59277b4`
- The worktree was already heavily modified and contained user work.  It was
  preserved.
- AMD GPU: `AMD Radeon (TM) Graphics`
- Driver: `31.0.21925.1001`, dated `2026-05-20`
- Current AMD path uses Media Foundation D3D11VA decode, D3D11 composition and
  AMF encode in the long-lived Python/Qt application process.

## RESULT

The desktop-instability risk is **confirmed**, but the evidence does not show
an `explorer.exe` crash or a classic kernel GPU-driver TDR.

The best-supported failure chain is:

```text
TeleM / other process commit growth
        +
only 1 GiB effective page file
        +
~8.6 GiB commit charged to System
        ↓
system commit exhaustion (Event 2004)
        ↓
DWM fatal memory exhaustion and/or python.exe D3D11 access violation
        ↓
desktop/taskbar/windows appear frozen, which looks like Explorer/GPU hang
```

### Confidence

- **HIGH:** the machine repeatedly exhausts virtual-memory commit during the
  render/test workload.
- **HIGH:** DWM crashes are capable of producing the reported apparent desktop
  / Explorer freeze.
- **HIGH:** TeleM render processes materially contribute to the exhaustion.
- **MEDIUM-HIGH:** retained native Media Foundation/D3D11/driver-owned resources
  across renders in one persistent process are an important contributor.
- **NOT PROVEN:** the exact retained native object or allocation owner.
- **NOT PROVEN:** a kernel-mode AMD driver hang/reset.
- **NOT PROVEN:** an `explorer.exe` fault.

## WINDOWS EVENT EVIDENCE

Window inspected: from `2026-09-05` through the audit on `2026-09-07`.

| Evidence | Count | Detail |
|---|---:|---|
| Resource Exhaustion Detector, Event 2004 | 70 | Windows explicitly reported exhausted virtual memory |
| `python.exe` crash in `d3d11.dll` | 5 | Exception `0xc0000005`, identical fault offset `0x728ef` |
| `dwm.exe` crash | 6 | Five in `dwmcore.dll` with `0xc00001ad`; one separate `dwmredir.dll` failure |
| `explorer.exe` Application Error 1000 | 0 | No Explorer crash found |
| `explorer.exe` Application Hang 1002 | 0 | No Explorer hang found |
| Display provider / Event 4101 | 0 | No "display driver stopped responding and recovered" evidence |
| recent `LiveKernelReports` | 0 | No retained kernel GPU crash report found |

The Windows SDK installed on this machine defines `0xC00001AD` as
`STATUS_FATAL_MEMORY_EXHAUSTION` in
`Windows Kits/10/Include/10.0.26100.0/shared/ntstatus.h`.

### Direct temporal correlation

Representative event pairs:

| Resource exhaustion | Subsequent fault | Delay |
|---|---|---:|
| 2026-09-06 11:55:34 | `python.exe` / `d3d11.dll` 11:55:44 | 10 s |
| 2026-09-06 12:44:30 | `dwm.exe` / `dwmcore.dll` 12:47:22 | 2 min 52 s |
| 2026-09-06 12:49:30 | `dwm.exe` / `dwmcore.dll` 12:49:45 | 15 s |
| 2026-09-06 19:46:14 | `dwm.exe` / `dwmcore.dll` 19:46:42 | 28 s |
| 2026-09-07 13:03:12 | `python.exe` / `d3d11.dll` 13:04:53 | 1 min 41 s |
| 2026-09-07 16:24:11 | `dwm.exe` / `dwmcore.dll` 16:24:52 | 41 s |
| 2026-09-07 16:24:11 | `python.exe` / `d3d11.dll` 16:26:18 | 2 min 7 s |

The 2026-09-06 12:47 sequence also included failures of `LogonUI.exe` and
`TabTip.exe`, consistent with broad desktop-session resource exhaustion rather
than an isolated Explorer fault.

WER reports for the D3D11 crashes show that the faulting Python processes had
the exact TeleM AMD stack loaded, including:

- `native/d3d11_amf_pipeline/bin/telem_amd_native.dll`
- Media Foundation (`MF`, `MFReadWrite`, `MFPlat`, `MFCore`)
- `d3d11.dll` and `dxgi.dll`
- AMD AMF and driver user-mode modules
- TeleM source videos such as `GX010114.MP4` and `GX010115.MP4`

No crash dump was retained with the WER reports, and WinDbg/CDB is not
installed.  Therefore the exact native call stack at `d3d11.dll+0x728ef` is
**NOT PROVEN**.

## COMMIT / PAGE-FILE EVIDENCE

Current live counters during the audit:

```text
Physical RAM:                   29,957,386,240 bytes
Available physical memory:     15,501,033,472 bytes
Committed bytes:               28,619,845,632 bytes
Commit limit:                  31,031,128,064 bytes
Committed bytes in use:        92%
Commit headroom:                2,411,282,432 bytes
```

This explains why allocation failures can occur even while Task Manager still
appears to show substantial free physical RAM: commit, not resident RAM, is
the exhausted resource.

Configured page files:

```text
C:\pagefile.sys  1 GiB
D:\pagefile.sys 32 GiB
```

Effective/active page files in the current boot:

```text
C:\pagefile.sys  1 GiB
```

`Win32_PageFileUsage` and `Win32_PageFile` expose only the C: file, the current
commit limit equals physical RAM plus approximately 1 GiB, and
`D:\pagefile.sys` is not present through the file API.  Thus the configured
32-GiB D: page file is not active in the current boot.  The reason it did not
become active is **NOT PROVEN**; it may be a pending/failed page-file setup or
boot-time availability issue.

Resource Exhaustion Event 2004 repeatedly attributed approximately 8.6 GiB to
`System` and between approximately 1.0 and 4.9 GiB to individual Python render
processes.  The exact reason for the unusually large, stable `System` charge is
**NOT PROVEN**.

## TeleM PROCESS-LIFETIME EVIDENCE

Existing same-process lifecycle measurements were rechecked rather than
re-running a destructive stress case:

| State | RSS | Private/commit | Threads | Handles |
|---|---:|---:|---:|---:|
| fresh process | 156.7 MiB | 663.8 MiB | 21 | 365 |
| after render 1 | 977.5 MiB | 1847.6 MiB | 36 | 805 |
| after render 2 | 1397.8 MiB | 2610.4 MiB | 40 | 980 |
| after render 3 | 1817.9 MiB | 3342.9 MiB | 40 | 1157 |

Python `tracemalloc` stayed near 168–170 MiB, so the retained growth is outside
the tracked Python heap.  Prior ablations found that it persisted with export
Preview disabled, GPU HUD disabled and AMF bypassed.  Top-level native COM
object accounting and D3D11 device refcount checks were clean.  The strongest
remaining boundary is the successful Media Foundation D3D11VA decode path and
driver/MF-owned deferred resources, but the exact allocation owner remains
**NOT PROVEN**.

The later full-HUD memory fix removed per-frame Pillow byte-allocation churn and
allowed a single long render to plateau.  It did not prove that native/process-
global allocations return to the baseline between multiple renders in the
same GUI process.

## CODE LIFECYCLE AUDIT

### Successful-render path

The Python exporter has idempotent cleanup and invokes `telem_amd_close()` both
at normal video-loop completion and from `finally` protection.  The native
close path:

1. drains AMF when required,
2. closes encoded output,
3. releases the MF Source Reader and DXGI device manager,
4. releases owned textures,
5. destroys VP and AMF objects through the context destructor,
6. releases the D3D11 immediate context/device,
7. calls `MFShutdown()`.

Optional Source Reader `Flush()` and D3D11 `ClearState()+Flush()` teardown
experiments already showed no meaningful reduction in the persistent
same-process growth.  Enabling them blindly is therefore not a proven fix.

### Confirmed failure-path cleanup defect

`telem_amd_create()` calls `MFStartup()` before initialization.  The encoded-
output failure path balances it with `MFShutdown()`, but the following later
failure returns delete the context and return without balancing `MFShutdown()`:

- `D3D11CreateDevice` failure,
- VP pipeline initialization failure,
- VP setup failure,
- AMF initialization failure.

The raw context-owned D3D11 device/context pointers are also not handled by a
RAII context destructor on those partial-construction paths.  This is a real
cleanup defect which can compound process poisoning after a failed renderer
start, especially once memory is already low.  It does not by itself explain
the measured retention after successful renders and was not modified in this
diagnostic task.

## WHY IT LOOKS LIKE EXPLORER OR GPU DRIVER HANG

`dwm.exe` owns desktop composition.  If it dies from fatal memory exhaustion,
windows, taskbar repaint and desktop interaction can freeze or disappear even
though `explorer.exe` itself never faults.  In the examined window there are no
Explorer crash/hang records, while DWM has repeated fatal-memory crashes.

The simultaneous `python.exe` faults in `d3d11.dll` show that D3D11 operations
also fail in the exhausted state.  However, absence of Display 4101 and
LiveKernelReports means the evidence does not establish a kernel-mode AMD
driver reset/hang.  Calling this a proven "GPU driver hang" would overstate the
data.

The fault can appear just after rendering because the process retains native
commit after the frame loop and then performs D3D/MF/AMF teardown while system
commit is already critically low.  Without a crash dump, whether the observed
`d3d11.dll` access violation occurs inside teardown itself is **NOT PROVEN**.

## IMMEDIATE SAFE MITIGATION

Until the process-lifetime issue is fixed:

1. Use one AMD render per TeleM process; close and relaunch TeleM after every
   completed, cancelled, or failed AMD render.
2. Avoid simultaneous render/probe Python processes.
3. Make a sufficiently sized page file effective on a disk available during
   Windows boot.  The configured D: page file is currently ineffective.
   Increasing commit capacity mitigates desktop collapse but does not fix the
   TeleM/native retention.
4. If the desktop becomes unresponsive after a render, terminate/restart the
   TeleM Python process first.  Restarting Explorer alone does not address a
   DWM/commit failure.

No page-file or operating-system setting was changed by this audit.

## RECOMMENDED ENGINEERING FIX ORDER

1. **Containment:** run the AMD native renderer in a short-lived child process
   per export.  Process exit is the only currently proven full reclamation
   boundary for MF/D3D11/AMF/driver-owned state.
2. **Repair partial initialization:** make native context creation RAII-safe and
   balance every `MFStartup()` with `MFShutdown()` on all returns.
3. **Capture the exact owner:** with explicit approval, enable full local dumps
   for `python.exe` and collect WPR/ETW GPU/MF traces during a controlled
   same-process A/B run.  Current WER metadata has no call stack or heap data.
4. **Verify:** repeat the same-process multi-render audit and require private
   commit and handles to return to a stable post-warm-up baseline before
   declaring the issue fixed.

The page-file configuration should be corrected as operational hardening in
parallel, but must not be accepted as the application fix.

## CHANGED FILES

- `Raporty/RAPORT_AMD_POST_RENDER_DESKTOP_GPU_STABILITY_AUDIT.md` — this report
  only.

No production source, test, driver, registry or page-file setting was changed.

## TESTS / CHECKS

- PASS — Application Error and Application Hang event-log audit.
- PASS — Resource Exhaustion Detector correlation audit.
- PASS — Display-provider / LiveKernelReports absence check.
- PASS — WER metadata and loaded-module inspection.
- PASS — current commit, page-file and GPU-memory counter inspection.
- PASS — successful and failed native teardown code-path inspection.
- PASS — rechecked existing persistent-process resource measurements.
- PASS — after the current boot and the short FIT validation render, no new
  Event 2004, DWM crash, or Python/D3D11 crash was recorded.
- NOT RUN — intentional repeated heavy render designed to reproduce the DWM
  crash; skipped because it could destabilize the active desktop again.
- NOT TESTED — page-file activation/reboot, because this audit did not modify
  system settings.
- NOT TESTED — child-process renderer containment; not implemented.
- NOT TESTED — fix for partial native initialization cleanup; not implemented.

## PERFORMANCE

No performance benchmark was run.  This was a stability diagnosis and no
renderer behavior changed.

## REGRESSIONS / RISKS

- Repeated AMD renders in one persistent GUI process remain unsafe under the
  current commit limit.
- A single large render or multiple concurrent probes can also exhaust commit.
- A larger active page file should make DWM collapse less likely, but can mask
  rather than remove retained native allocations.
- The exact MF/D3D11/AMD ownership boundary still requires a dump/ETW capture.
- Partial native initialization failures have an independent cleanup leak.

## BACKEND ISOLATION

- AMD path: inspected only; no behavior changed.
- NVIDIA/NVENC/CUDA: not modified.
- Intel/QSV: not modified.
- CPU/reference path: not modified.

## FINAL PASS / FAIL SUMMARY

```text
AUDIT OBJECTIVE:                         PASS
DESKTOP INSTABILITY RISK:               CONFIRMED
EXPLORER.EXE CRASH/HANG:                 NOT PROVEN (no events found)
DWM FATAL MEMORY EXHAUSTION:             CONFIRMED
PYTHON/TELEM D3D11 CRASHES:              CONFIRMED
KERNEL AMD DRIVER HANG/TDR:              NOT PROVEN
SYSTEM COMMIT EXHAUSTION:                CONFIRMED
D: 32-GiB PAGE FILE EFFECTIVE:           FAIL
PERSISTENT-PROCESS MULTI-RENDER SAFETY:   FAIL
EXACT NATIVE RETENTION OWNER:            NOT PROVEN
PRODUCTION FIX:                          NOT IMPLEMENTED
```
