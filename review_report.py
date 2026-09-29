"""Create a shareable HTML review package from measured experiment artifacts."""
import argparse
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def svg_fragment(path):
    text = path.read_text()
    return "<svg" + text.split("<svg", 1)[1]


def main(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    physical = json.loads((args.physical / "summary.json").read_text())
    benchmark = json.loads((args.benchmark / "summary.json").read_text())
    search = json.loads((args.search / "summary.json").read_text())
    controls = json.loads((args.controls / "summary.json").read_text())
    if not physical["verification"]["drc_pass"] or not physical["verification"]["lvs_pass"]:
        raise ValueError("Baseline physical verification must pass")
    if controls["wrong_device_width"]["lvs_pass"] or controls["too_narrow_metal"]["drc_pass"]:
        raise ValueError("Negative verification controls must reject deliberate errors")
    best_index = search["best_candidate"]
    if best_index is None:
        raise ValueError("A feasible physical search result is required for the review report")
    best_folder = args.search / "designs" / f"candidate-{best_index:03d}"
    best = search["best_design"]
    specification = json.loads((args.search / "specification.json").read_text())
    requirements_table = f"""<table><tr><th>Requirement</th><th>Limit</th><th>Worst measured result</th></tr>
<tr><td>Copy-current error, 0.6–1.6 V output</td><td>≤ {specification['max_copy_error_percent']:g}%</td><td>{best['worst_error_percent']:.2f}%</td></tr>
<tr><td>Reference bias voltage</td><td>≤ {specification['max_reference_voltage_v']:g} V</td><td>{best['worst_reference_voltage_v']:.3f} V</td></tr>
<tr><td>Current-transfer bandwidth</td><td>≥ {specification['minimum_bandwidth_hz']/1e6:g} MHz</td><td>{best['minimum_bandwidth_hz']/1e6:.1f} MHz (sampled crossing)</td></tr></table>"""
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(figsize=(8, 4.4), constrained_layout=True)
    for metrics in best["electrical"]:
        data = np.loadtxt(best_folder / f"{metrics['corner']}-{metrics['temperature_c']}" / "sweep.dat", skiprows=1)
        ax.plot(data[:, 1], -data[:, 2]*1e6, label=f"{metrics['corner'].upper()}, {metrics['temperature_c']}°C")
    current = best["electrical"][0]["reference_ua"]
    ax.axhline(current, color="black", linestyle="--", linewidth=1, label="Reference current")
    ax.axvspan(0.6, 1.6, alpha=0.07, color="green", label="Specified output range")
    ax.set(xlabel="Output voltage (V)", ylabel="Copied current (µA)", title="Capacitance-extracted SKY130 DC characterization")
    ax.legend(ncol=3, fontsize=8)
    fig.savefig(output / "dc.svg")
    fig.savefig(output / "dc.png", dpi=180)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 4.4), constrained_layout=True)
    for source, label in (("schematic", "Schematic"), ("extracted_capacitance", "Extracted capacitance")):
        data = np.loadtxt(args.physical / "simulation" / f"{source}-tt-27" / "ac.dat", skiprows=1)
        gain = np.maximum(np.hypot(data[:, 1], data[:, 2]), 1e-15)
        ax.semilogx(data[:, 0], 20*np.log10(gain), label=label)
    ax.set(xlabel="Frequency (Hz)", ylabel="Current transfer (dB)", title="Schematic versus extracted AC response (initial design, TT / 27°C)")
    ax.legend()
    fig.savefig(output / "ac.svg")
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4), constrained_layout=True)
    for strategy, color in (("bayesian", "#2569a1"), ("random", "#a16a25")):
        experiments = [e for e in search["experiments"] if e["strategy"] == strategy]
        area = np.array([[r["best_feasible_area_um2"] if r["best_feasible_area_um2"] is not None else np.nan for r in e["trace"]] for e in experiments])
        calls = np.arange(1, area.shape[1]+1)
        axes[0].plot(calls, np.nanmedian(area, axis=0), color=color, label=strategy)
        axes[0].fill_between(calls, np.nanquantile(area, 0.25, axis=0), np.nanquantile(area, 0.75, axis=0), color=color, alpha=0.12)
        axes[1].plot(calls, np.mean(np.isfinite(area), axis=0)*100, color=color, label=strategy)
    if search["exhaustive_grid_check"]:
        axes[0].axhline(best["geometry"]["area_um2"], color="black", linestyle="--", label="Discrete-grid optimum")
    axes[0].set(xlabel="Design evaluations", ylabel="Feasible layout area (µm²)", title="Median among successful searches; IQR")
    axes[1].set(xlabel="Design evaluations", ylabel="Trials with a feasible design (%)", title="Success over paired search seeds", ylim=(0, 105))
    for ax in axes:
        ax.legend(fontsize=8)
    fig.savefig(output / "search.svg")
    plt.close(fig)
    comparisons = "".join(f"<tr><td>{html.escape(c['family'])}</td><td>{c['baseline']}</td><td>{c['mean_gain_percent']:.2f}%</td><td>[{c['ci95'][0]:.2f}, {c['ci95'][1]:.2f}]</td></tr>" for c in benchmark["comparisons"])
    search_rows = ""
    for strategy, statistics in search["strategy_summary"].items():
        area = statistics["median_feasible_area_um2"]
        budget = next(e["budget"] for e in search["experiments"] if e["strategy"] == strategy)
        search_rows += f"<tr><td>{strategy}</td><td>{statistics['successful_trials']} / {statistics['trials']}</td><td>{budget}</td><td>{f'{area:.2f}' if area is not None else 'No feasible design'}</td></tr>"
    title = "Analog automation · SKY130 review demonstrator"
    document = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>
<style>body{{margin:0;background:#edf2f7;color:#14253a;font:16px/1.55 system-ui}}main{{max-width:1120px;margin:auto;padding:40px 24px}}h1{{font-size:38px;line-height:1.2}}h2{{font-size:24px}}section{{background:white;border-radius:14px;padding:28px;margin:24px 0}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}.metric{{font-size:30px;color:#16604b;font-weight:700}}.eyebrow{{color:#46647f;font-size:13px;letter-spacing:2px}}svg{{max-width:100%;height:auto}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #d8e2ec}}.layout{{background:#111;padding:12px;border-radius:8px}}.layout svg{{max-height:480px;display:block;margin:auto}}a{{color:#1766a8}}code{{font-size:13px;overflow-wrap:anywhere}}@media(max-width:700px){{.grid{{grid-template-columns:1fr}}h1{{font-size:28px}}section{{padding:18px}}}}</style>
<main><p class="eyebrow">MEASURED OUTPUT · INDEPENDENT VERIFICATION · REPRODUCIBLE SLURM RUNS</p><h1>{title}</h1>
<p>Specification → learning-guided dimension search → routed transistor layout → DRC/LVS → extracted simulation.</p>
<section><h2>Best measured feasible current mirror</h2><div class="grid"><div><p class="metric">{best['geometry']['area_um2']:.2f} µm²</p><p>W = {best['config'][0]} µm; L = {best['config'][1]} µm; {best['config'][2]} columns per device.</p><p><strong>{best['verification']['drc_error_count']} full-deck DRC errors · LVS {'PASS' if best['verification']['lvs_pass'] else 'FAIL'}</strong></p><p>Worst copy error: {best['worst_error_percent']:.2f}% over 0.6–1.6 V, three process corners, and −20/27/85°C. Lowest sampled 3dB crossing (or scan bound): {best['minimum_bandwidth_hz']/1e6:.1f} MHz. Maximum bias voltage: {best['worst_reference_voltage_v']:.3f} V.</p><p><a href="../search/designs/candidate-{best_index:03d}/layout.gds">Download GDS</a> · <a href="../search/designs/candidate-{best_index:03d}/lvs.log">LVS report</a> · <a href="../search/designs/candidate-{best_index:03d}/magic.log">DRC report</a></p></div><div class="layout">{svg_fragment(best_folder / 'layout.svg')}</div></div></section>
<section><h2>Electrical evidence</h2><p>The copied current target is {current:g} µA. All listed requirements must hold at TT/SS/FF and −20/27/85°C. Results use official SKY130 model corners and a netlist extracted from the emitted GDS.</p>{requirements_table}{svg_fragment(output/'dc.svg')}{svg_fragment(output/'ac.svg')}<p>The AC comparison uses the initial W=2 µm / L=0.5 µm design. DC does not measure the impact of capacitance. Resistance parasitics are not extracted in this milestone.</p></section>
<section><h2>Learning on real generated layouts</h2><p>A Gaussian-process surrogate predicts a penalized area objective and proposes the next candidate by expected improvement. Each queried candidate is checked and simulated. The random baseline shares four initial candidates and the same query budget. Cached evaluations save computation while counting as queries for each strategy. The model uses only observations selected in its own trial.</p>{svg_fragment(output/'search.svg')}<table><tr><th>Strategy</th><th>Successful trials</th><th>Calls per trial</th><th>Median feasible area (µm²)</th></tr>{search_rows}</table><p>{search['unique_evaluations']} unique evaluated candidates from a {search['candidates']}-point discrete space; {search['feasible_evaluations']} meet all measured constraints. {'Every discrete candidate was audited after the searches; the reported minimum is exact for this grid.' if search['exhaustive_grid_check'] else 'The grid was not exhaustively checked.'} This experiment covers one circuit family and does not establish a continuous-space optimum or broad learning superiority. Conditional area statistics exclude unsuccessful trials; inspect success rates alongside area.</p></section>
<section><h2>Separate placement-learning experiment</h2><p>{benchmark['runs']} runs, {benchmark['test_circuits']} synthetic test graphs, {benchmark['seeds']} seeds per graph. The frozen learned move policy generally did not improve on the baselines. Positive percentages below indicate lower wire cost. These are block-graph results, separate from the transistor layout flow.</p><table><tr><th>Family</th><th>Baseline</th><th>Mean learned gain</th><th>95% interval (%)</th></tr>{comparisons}</table></section>
<section><h2>What an engineer can review</h2><p>Generated GDS and SVG; schematic and extracted SPICE; full DRC output; Netgen topology and property comparison; DC and AC sweeps for nine process/temperature combinations; complete search traces and model predictions; paired benchmark metrics and source hashes.</p><p>Negative controls passed: a deliberately incorrect transistor width was rejected by LVS, and a 20nm local-interconnect shape was rejected by DRC. Testbench binding follows declared pin names, including extraction-induced reordering.</p><p>PDK build: <code>{physical['pdk_build']}</code>. GLayout {physical['versions']['glayout']}. Device generation and routing are supplied by <a href="https://github.com/idea-fasoc/OpenFASOC">OpenFASOC / GLayout</a>; this project supplies learning experiments, search orchestration, the local SKY130 mapping adapter, checks, characterization, and reporting.</p><p>Open physical checks are not foundry signoff. Outstanding: full resistance/capacitance extraction, mismatch/yield analysis, foundry-specific density/antenna/latchup coverage, larger circuit families, and silicon measurements. The design has not been submitted for fabrication.</p></section></main></html>"""
    (output / "index.html").write_text(document)
    manifest = dict(physical=str(args.physical.resolve()), benchmark=str(args.benchmark.resolve()),
                    search=str(args.search.resolve()), best_candidate=best_index)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Review report: {output / 'index.html'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--physical", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--search", type=Path, required=True)
    parser.add_argument("--controls", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/review"))
    main(parser.parse_args())
