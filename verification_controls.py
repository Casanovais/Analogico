"""Negative controls prove the physical verifier detects real errors."""
import argparse
import json
import os
import re
import shutil
from pathlib import Path

from physical_flow import ROOT, verify


def run(args):
    pdk_root = args.pdk_root.resolve()
    os.environ.update(PDK_ROOT=str(pdk_root), PDKPATH=str(pdk_root / "sky130A"))
    output = args.output.resolve()
    results = {}
    for case in ("wrong_device_width", "too_narrow_metal"):
        folder = output / case
        folder.mkdir(parents=True, exist_ok=True)
        for filename in ("layout.gds", "schematic.spice"):
            shutil.copyfile(args.base / filename, folder / filename)
        if case == "wrong_device_width":
            path = folder / "schematic.spice"
            original = path.read_text()
            changed = re.sub(r"\bw=([0-9.]+)", lambda m: f"w={float(m.group(1))+0.3}", original)
            if changed == original:
                raise RuntimeError("Could not insert the intended schematic width error")
            path.write_text(changed)
        else:
            import gdstk
            library = gdstk.read_gds(folder / "layout.gds")
            top = next(c for c in library.top_level() if c.name == "CMIRROR")
            maximum = top.bounding_box()[1]
            x, y = maximum[0]+2, maximum[1]+2
            top.add(gdstk.rectangle((x,y), (x+0.02,y+0.02), layer=67, datatype=20))
            library.write_gds(folder / "layout.gds")
        result = verify(folder, pdk_root / "sky130A")
        results[case] = result
        if case == "wrong_device_width" and result["lvs_pass"]:
            raise RuntimeError("LVS accepted a deliberate device-width mismatch")
        if case == "too_narrow_metal" and result["drc_pass"]:
            raise RuntimeError("DRC accepted a deliberate minimum-width violation")
    (output / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "results/verification-controls")
    parser.add_argument("--pdk-root", type=Path, default=ROOT / "pdks")
    run(parser.parse_args())
