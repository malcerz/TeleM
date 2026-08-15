# TeleM GUI worktree — agent rules

## Scope

This worktree is dedicated ONLY to GUI development and GUI refactoring.

The parallel branch/worktree is currently performing AMD/GPU pipeline optimization.
Do NOT modify, refactor, rename, reorganize or "clean up" code related to that work.

## STRICTLY PROTECTED AREAS

Do not modify code related to:

* GPU rendering
* GPU compositor
* AMD / AMF support
* NVIDIA / NVENC support
* Intel / QuickSync support
* FFmpeg rendering pipeline
* hardware encoding
* hardware decoding
* frame conversion
* pixel format conversion
* CPU ↔ GPU transfers
* video compositing backend
* rendering benchmarks
* performance optimizations
* render worker architecture
* preview decoding/rendering backend

If GUI work requires a change in any of these areas:

1. DO NOT implement the backend change.
2. Keep the existing backend API intact.
3. Adapt the GUI around the existing interface whenever possible.
4. If impossible, report exactly what backend change would be required.

## Allowed work

You may modify:

* windows
* dialogs
* widgets
* layouts
* tabs
* menus
* toolbars
* GUI state
* user interaction
* indicator configuration panels
* Project tab layout
* Loading tab
* Rendering settings UI
* Application settings UI
* visual organization of preview controls

## Architecture rule

GUI must remain separated from rendering implementation.

Prefer:

GUI
↓
controller / interface
↓
existing rendering backend

Do not move rendering logic into GUI classes.

## Existing APIs

Treat existing rendering/GPU APIs as stable interfaces.

Do not change their signatures unless explicitly instructed by the user.

## Before editing

Before modifying a file, determine whether it contains or participates in the AMD/GPU optimization work.

If yes, do not modify it unless the requested GUI task cannot be completed otherwise.

When uncertain, treat the file as protected.

## Git

This branch contains GUI changes only.

Do not merge, cherry-pick or modify the AMD optimization branch.
Do not revert changes originating from the parallel optimization work.



\# TeleM GUI worktree — agent rules



\## Scope



This worktree is dedicated ONLY to GUI development and GUI refactoring.



\## Protected files



DO NOT MODIFY:



\- core/gpu\_compositor.py

\- rendering/ffmpeg\_renderer.py

\- rendering/gpu\_pipeline.py

\- video/decoder.py

\- benchmark/\*



\## Allowed work



You may modify:



\- GUI windows

\- dialogs

\- widgets

\- layouts

\- tabs

\- menus

