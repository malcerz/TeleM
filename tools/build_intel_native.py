"""Build only Intel native, using explicit LLVM-MinGW, FFmpeg and libvpl headers.

Requires pefile (build-time only). Example:
python tools/build_intel_native.py --toolchain PATH --ffmpeg-headers PATH --vpl-headers PATH
Output is a candidate, never an implicit overwrite of the installed runtime.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess


def main():
    import pefile
    parser=argparse.ArgumentParser()
    parser.add_argument("--toolchain",type=Path,required=True)
    parser.add_argument("--ffmpeg-headers",type=Path,required=True)
    parser.add_argument("--vpl-headers",type=Path,required=True,help="Directory containing vpl/mfxvideo.h")
    parser.add_argument("--output",type=Path,default=Path("scratch/intel_native_build"))
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    tool=args.toolchain.resolve()/"bin"; out=args.output.resolve(); out.mkdir(parents=True,exist_ok=True)
    for name in ("avformat","avcodec","avutil"):
        dll=next((root/"runtime/intel/bin").glob(name+"-*.dll"))
        pe=pefile.PE(str(dll),fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]])
        exports=[s.name.decode() for s in pe.DIRECTORY_ENTRY_EXPORT.symbols if s.name]
        definition=out/(name+".def")
        definition.write_text("LIBRARY "+dll.name+"\nEXPORTS\n"+"\n".join(exports)+"\n")
        subprocess.run([str(tool/"llvm-dlltool.exe"),"-m","i386:x86-64","-d",str(definition),"-l",str(out/("lib"+name+".a"))],check=True)
    generated=out/"include/libavutil"; generated.mkdir(parents=True,exist_ok=True)
    (generated/"avconfig.h").write_text("#define AV_HAVE_BIGENDIAN 0\n#define AV_HAVE_FAST_UNALIGNED 1\n")
    source=root/"src/native/intel/d3d11_intel_pipeline/telem_intel_native.c"
    cmd=[str(tool/"clang.exe"),"-shared","-O2","-mavx2","-mfma","-Wno-deprecated-declarations",
         "-I"+str(out/"include"),"-I"+str(args.ffmpeg_headers.resolve()),"-I"+str(args.vpl_headers.resolve()),
         str(source),"-L"+str(out),"-lavformat","-lavcodec","-lavutil","-ld3d11","-ldxgi","-ldxguid","-lole32",
         "-o",str(out/"telem_intel_native.dll")]
    subprocess.run(cmd,check=True)
    manifest={"command":cmd,"source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
              "dll_sha256":hashlib.sha256((out/"telem_intel_native.dll").read_bytes()).hexdigest(),
              "compiler":subprocess.check_output([str(tool/"clang.exe"),"--version"],text=True)}
    (out/"build_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps(manifest,indent=2))


if __name__=="__main__": main()
