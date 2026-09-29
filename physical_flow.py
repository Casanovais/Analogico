"""Generate, verify and simulate a real SKY130 current-mirror layout.

The GLayout generator supplies device construction and routing. Magic's PDK
deck and Netgen independently check the emitted GDS; exit codes alone are not
treated as verification passes. This flow does not imply foundry signoff.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PDK_BUILD = "7519dfb04400f224f140749cda44ee7de6f5e095"


def mirror_instance(netlist):
    match = re.search(r"^\.subckt\s+CMIRROR\s+([^\n]+)", netlist, re.I | re.M)
    if match is None:
        raise ValueError("Missing CMIRROR subcircuit declaration")
    pins = match.group(1).split()
    mapping = {"VREF": "VREF", "VOUT": "VOUT", "VSS": "0", "B": "0"}
    if len(pins) != 4 or set(p.upper() for p in pins) != set(mapping):
        raise ValueError(f"Unexpected CMIRROR pins: {pins}")
    # Extraction may change positional pin order. Bind by the declared names.
    return "XMIRROR " + " ".join(mapping[p.upper()] for p in pins) + " CMIRROR"


def command(args, cwd, log, input_text=None, timeout=180):
    result = subprocess.run([str(v) for v in args], cwd=cwd, input=input_text,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=timeout, env=os.environ.copy())
    log.write_text(result.stdout)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}), see {log}")
    if re.search(r"^(?:Error:|ERROR:|Error while reading)", result.stdout, re.M):
        raise RuntimeError(f"Tool reported an error despite its exit status; see {log}")
    return result.stdout


def simulate(netlist, output, pdk, corner="tt", temperature=27, reference_ua=20):
    """Measure copy current versus output voltage using the actual PDK models."""
    output.mkdir(parents=True, exist_ok=True)
    model_dir = pdk / "libs.ref/sky130_fd_pr/spice"
    model = model_dir / f"sky130_fd_pr__nfet_01v8__{corner}.corner.spice"
    # Volare's selected primitive library is flattened. Load its official
    # NFET corner directly and provide a search path for nested includes.
    (output / ".spiceinit").write_text(f"set ngbehavior=hsa\nset ng_nomodcheck\nset sourcepath = ( . {model_dir} )\n")
    deck = f"""SKY130 current-mirror DC characterization
.include "{model}"
.option scale=1e-6
.param mc_mm_switch=0 mc_pr_switch=0
.include "{model_dir / 'sky130_fd_pr__nfet_01v8__mismatch.corner.spice'}"
.temp {temperature}
{netlist}
IREF 0 VREF {reference_ua}u ac 1
VOUT VOUT 0 1
{mirror_instance(netlist)}
.dc VOUT 0.2 1.6 0.05
.meas dc copy_current find i(VOUT) at=1.0
.meas dc ref_voltage find v(VREF) at=1.0
.control
set wr_vecnames
set wr_singlescale
run
wrdata sweep.dat v(VOUT) i(VOUT) v(VREF)
ac dec 30 1k 10g
let transfer = -i(VOUT)
wrdata ac.dat real(transfer) imag(transfer)
quit
.endc
.end
"""
    (output / "testbench.spice").write_text(deck)
    text = command(["ngspice", "-b", "testbench.spice"], output, output / "ngspice.log")
    metrics = {}
    for name in ("copy_current", "ref_voltage"):
        match = re.search(rf"{name}\s*=\s*([-+\d.eE]+)", text, re.I)
        if match is None:
            raise RuntimeError(f"Missing ngspice measurement {name}: {output / 'ngspice.log'}")
        metrics[name] = float(match.group(1))
    metrics["current_ratio_at_1v"] = -metrics["copy_current"] / (reference_ua * 1e-6)
    import numpy as np
    sweep = np.loadtxt(output / "sweep.dat", skiprows=1)
    voltages, currents = sweep[:, 1], sweep[:, 2]
    active = (voltages >= 0.6 - 1e-8) & (voltages <= 1.6 + 1e-8)
    ratios = -currents / (reference_ua * 1e-6)
    metrics["worst_error_percent_0p6_to_1p6v"] = float(np.max(np.abs(ratios[active] - 1)) * 100)
    metrics["max_reference_voltage_v"] = float(np.max(sweep[:, 3]))
    ac = np.loadtxt(output / "ac.dat", skiprows=1)
    gains = np.hypot(ac[:, 1], ac[:, 2])
    metrics["ac_gain_at_1mhz"] = float(np.interp(1e6, ac[:, 0], gains))
    below = np.flatnonzero(gains <= gains[0] / np.sqrt(2))
    metrics["bandwidth_3db_hz"] = float(ac[below[0], 0]) if len(below) else None
    metrics.update(corner=corner, temperature_c=temperature, reference_ua=reference_ua)
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    return metrics


def generate(width, length, columns, output):
    from glayout.pdk.sky130_mapped import sky130_mapped_pdk
    from glayout.cells.elementary.current_mirror.current_mirror import current_mirror, add_cm_labels
    # Local adapter for the upstream mapping: substrate ties use tap, not
    # source/drain diffusion. SKY130 defines tap.drawing as GDS 65/44.
    # See https://skywater-pdk.readthedocs.io/en/main/rules/layers.html
    sky130_mapped_pdk.glayers["active_tap"] = (65, 44)
    cell = current_mirror(sky130_mapped_pdk, numcols=columns, device="nfet",
                          width=width, length=length, with_dummy=True, with_tie=True)
    netlist = cell.info["netlist"].generate_netlist()
    cell = add_cm_labels(cell, sky130_mapped_pdk)
    cell.unlock()
    cell.name = "CMIRROR"
    cell.write_gds(output / "layout.gds")
    (output / "schematic.spice").write_text(netlist + "\n")
    # Real polygons, not a block-placement rendering.
    import gdstk
    gds = gdstk.read_gds(output / "layout.gds")
    # SKY130's ordinary p-well is the implicit substrate (NOT nwell), not
    # the upstream generator's unsupported 64/44 annotation rectangle.
    for gds_cell in gds.cells:
        annotations = [p for p in gds_cell.polygons if (p.layer, p.datatype) == (64, 44)]
        if annotations:
            gds_cell.remove(*annotations)
    tops = gds.top_level()
    if len(tops) != 1:
        raise ValueError("Expected one current-mirror top cell")
    top = tops[0]
    # GDSFactory uniquifies repeated cell names within one Python process.
    # Each candidate is exported separately with a canonical LVS top name.
    top.name = "CMIRROR"
    gds.write_gds(output / "layout.gds")
    top.write_svg(output / "layout.svg")
    bbox = top.bounding_box()
    return netlist, {"width_um": width, "length_um": length, "columns": columns,
                     "bbox_um": [list(p) for p in bbox],
                     "area_um2": float((bbox[1][0]-bbox[0][0])*(bbox[1][1]-bbox[0][1]))}


def verify(output, pdk):
    magic = ROOT / "tools/bin/magic"
    netgen = ROOT / "tools/bin/netgen"
    rc = pdk / "libs.tech/magic/sky130A.magicrc"
    script = f"""gds read {{{output / 'layout.gds'}}}
load CMIRROR
select top cell
drc on
drc style drc(full)
drc check
drc catchup
puts "DRC_COUNT=[drc list count total]"
puts "DRC_DETAILS=[drc listall why]"
drc off
extract all
ext2spice lvs
ext2spice subcircuit top on
ext2spice -o {{{output / 'extracted.spice'}}}
ext2spice cthresh 0
ext2spice -o {{{output / 'extracted_capacitance.spice'}}}
quit -noprompt
"""
    (output / "verify.tcl").write_text(script)
    text = command([magic, "-rcfile", rc, "-noconsole", "-dnull"], output,
                   output / "magic.log", input_text=script)
    count = re.search(r"DRC_COUNT=(\d+)", text)
    if count is None or not (output / "extracted.spice").is_file():
        raise RuntimeError("Magic verification did not produce the required evidence")
    setup = pdk / "libs.tech/netgen/sky130A_setup.tcl"
    # Some Netgen installs use a shell wrapper with bash syntax; others use
    # a native executable. Do not send a native binary to a shell interpreter.
    launcher = ["bash", netgen] if netgen.read_bytes().startswith(b"#!") else [netgen]
    command(launcher + ["-batch", "lvs", f"{output / 'extracted.spice'} CMIRROR",
             f"{output / 'schematic.spice'} CMIRROR", setup, output / "lvs.log", "-json"],
            output, output / "netgen.log")
    if not (output / "lvs.log").is_file():
        raise RuntimeError("Netgen did not produce an LVS report")
    report = (output / "lvs.log").read_text()
    lvs_pass = "Circuits match uniquely." in report and "Property errors were found" not in report
    return {"drc_error_count": int(count.group(1)), "lvs_pass": lvs_pass,
            "drc_pass": int(count.group(1)) == 0,
            "capacitance_only_extraction": True, "resistance_extraction": False}


def run(args):
    pdk_root = args.pdk_root.resolve()
    pdk = pdk_root / "sky130A"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ["PDK_ROOT"] = str(pdk_root)
    os.environ["PDKPATH"] = str(pdk)
    netlist, geometry = generate(args.width, args.length, args.columns, output)
    verification = verify(output, pdk)
    electrical = []
    # Retain failed verification artifacts, but never present unverified
    # extracted circuits as successful physical designs.
    if verification["drc_pass"] and verification["lvs_pass"]:
        for corner in ("tt", "ss", "ff"):
            for temperature in (-20, 27, 85):
                for source in ("schematic", "extracted_capacitance"):
                    folder = output / "simulation" / f"{source}-{corner}-{temperature}"
                    source_netlist = (output / f"{source}.spice").read_text()
                    metrics = simulate(source_netlist, folder, pdk, corner, temperature)
                    electrical.append(dict(source=source, **metrics))
    summary = {"technology": "SKY130A", "pdk_build": PDK_BUILD,
               "generator": "GLayout current_mirror (upstream)",
               "geometry": geometry, "verification": verification, "electrical": electrical,
               "versions": {name: importlib.metadata.version(name) for name in ("glayout", "gdsfactory", "gdstk")},
               "tool_commits": {name: (ROOT / f"tools/logs/{name}-commit.txt").read_text().strip() for name in ("magic", "netgen")},
               "layout_sha256": hashlib.sha256((output / "layout.gds").read_bytes()).hexdigest(),
               "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "pin_binding": "By declared subcircuit pin name; schematic and extraction may reorder pins",
               "limitations": ["Not foundry signoff", "No interconnect resistance extraction",
                               "No mismatch Monte Carlo", "No silicon measurements",
                               "Upstream device/routing generator; learning benchmark is a separate experiment"]}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    if not verification["drc_pass"] or not verification["lvs_pass"]:
        raise RuntimeError(f"Physical verification failed; inspect {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdk-root", type=Path, default=ROOT / "pdks")
    parser.add_argument("--output", type=Path, default=ROOT / "results/physical")
    parser.add_argument("--width", type=float, default=2)
    parser.add_argument("--length", type=float, default=0.5)
    parser.add_argument("--columns", type=int, default=2)
    args = parser.parse_args()
    if args.width <= 0 or args.length <= 0 or args.columns <= 0:
        parser.error("Device dimensions and columns must be positive")
    run(args)
