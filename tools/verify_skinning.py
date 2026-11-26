"""Compare AP's captured compute outputs with an independent CPU reproduction."""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess

from ap_tools.skinning import VARIANTS, decode_blend, skin


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dump", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--gpu", type=Path, help="Compiled skin_gpu.exe for a WARP comparison")
    args = parser.parse_args()
    checks = []
    for source in sorted(args.dump.glob("*-cs-t0=*-cs=*.buf")):
        match = re.search(r"^(\d+)-cs-t0=.*-cs=([0-9a-f]{16})\.buf$", source.name)
        if not match or match[2] not in VARIANTS:
            continue
        number, shader = match.groups()
        def read(slot):
            files = list(args.dump.glob(f"{number}-{slot}=*-cs={shader}.buf"))
            if len(files) != 1:
                raise ValueError(f"Ambiguous/missing {number} {slot}")
            return files[0].read_bytes()
        count, = struct.unpack_from("<I", read("cs-cb0"))
        result = skin(source.read_bytes(), read("cs-t1"), read("cs-t2"), VARIANTS[shader], count)
        if args.gpu:
            folder = args.out.parent / "gpu-inputs" / number
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "rest.buf").write_bytes(source.read_bytes()[:count * 40])
            (folder / "bones.buf").write_bytes(read("cs-t2"))
            canonical = bytearray()
            for weights, indices in decode_blend(read("cs-t1"), VARIANTS[shader], count):
                canonical.extend(struct.pack("<4f4I", *(list(weights) + [0.0] * (4 - len(weights))),
                                             *(list(indices) + [0] * (4 - len(indices)))))
            (folder / "blend.buf").write_bytes(canonical)
            program = Path(__file__).resolve().parents[1] / "Core/APMI/Shaders/MeshSkinner.hlsl"
            subprocess.run([str(args.gpu.resolve()), str(program), str(folder / "rest.buf"),
                            str(folder / "blend.buf"), str(folder / "bones.buf"), str(folder / "posed.buf")],
                           check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            result = (folder / "posed.buf").read_bytes()
        expected = read("u0")[:len(result)]
        lhs = struct.unpack(f"<{len(result)//4}f", result)
        rhs = struct.unpack(f"<{len(expected)//4}f", expected)
        max_error = max(abs(a-b) for a,b in zip(lhs, rhs))
        scale = max(1.0, max(abs(v) for v in rhs))
        ok = max_error <= 2e-5 * scale
        checks.append(dict(dispatch=int(number), shader=shader, influences=VARIANTS[shader], vertices=count,
                           max_error=max_error, relative_tolerance=2e-5, passed=ok))
    report = dict(dump=str(args.dump.resolve()), implementation="WARP HLSL" if args.gpu else "CPU", checks=checks,
                  passed=bool(checks) and all(c["passed"] for c in checks))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
