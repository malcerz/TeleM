# Bundled DJI telemetry parser

The `telemetry_parser` package here was built from
`AdrianEddy/telemetry-parser` commit
`d45ebf2afce85fa691838fd32b3da8ae2fcac773` for CPython 3.14,
Windows x64. It is part of the copied application folder and needs no
installation or network connection on the destination machine.

Upstream offers MIT or Apache-2.0 licensing. Both notices are included as
`LICENSE-MIT` and `LICENSE-APACHE`. Rebuild deliberately with
`scripts/build_dji_parser.ps1` when changing Python ABI or upstream source.

`telemetry_parser.cp314-win_amd64.pyd` SHA-256:
`32e8a0a21489bf325284469c46a8bba1561ad1ff98058ae18bf18b6639f2cbf2`.
