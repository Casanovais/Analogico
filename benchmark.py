"""Train a frozen move policy and evaluate disjoint circuits with paired seeds."""
import argparse
import csv
import hashlib
import html
import json
import platform
import statistics
import time
from pathlib import Path

import numpy as np

from analog_layout import optimize, write_svg
from benchmark_circuits import FAMILIES, make_circuit
from placement_learning import MovePolicy, features


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def run(args):
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    train_families = FAMILIES[:3]
    rows, rewards, training_ids = [], [], []
    start = time.perf_counter()
    for family in train_families:
        for seed in range(args.train_circuits):
            spec = make_circuit(family, seed)
            training_ids.append(spec["name"])
            observed = []
            optimize(spec, args.train_steps, seed=seed, policy="uniform", observations=observed)
            normalizer = max(1, sum(n.get("weight", 1) for n in spec["nets"]) * sum(spec["boundary"]))
            for cost, progress, action, reward in observed:
                rows.append(features(spec, cost, progress, action))
                rewards.append(reward / normalizer)
        print(f"Training observations: {family}, {len(rows)} total", flush=True)
    model = MovePolicy.fit(rows, rewards, {"training_circuit_ids": training_ids,
                                          "training_families": list(train_families),
                                          "held_out_family": FAMILIES[3],
                                          "samples": len(rows), "train_steps": args.train_steps})
    model.save(output / "move_policy.json")
    training_seconds = time.perf_counter() - start
    results, demos = [], []
    for family in FAMILIES:
        for circuit_index in range(args.test_circuits):
            spec = make_circuit(family, 10000 + circuit_index)
            assert spec["name"] not in training_ids
            for seed in range(args.seeds):
                for policy in ("uniform", "adaptive", "learned"):
                    started = time.perf_counter()
                    result = optimize(spec, args.steps, seed, policy, learned_policy=model)
                    seconds = time.perf_counter() - started
                    if result["violations"]:
                        raise RuntimeError("Invalid placement produced")
                    results.append(dict(circuit=spec["name"], family=family, seed=seed,
                                        policy=policy, steps=args.steps, initial_cost=result["initial_cost"],
                                        best_cost=result["best_cost"], improvement_percent=result["improvement_percent"],
                                        seconds=seconds, violations=len(result["violations"])))
                    if seed == 0 and circuit_index == 0:
                        folder = output / spec["name"] / policy
                        folder.mkdir(parents=True, exist_ok=True)
                        write_json(folder / "result.json", result)
                        write_json(folder / "input.json", spec)
                        placed = dict(spec, devices=result["devices"])
                        write_json(folder / "placement.json", placed)
                        write_svg(spec, spec["devices"], folder / "initial.svg")
                        write_svg(spec, result["devices"], folder / "optimized.svg")
                        if policy == "learned":
                            demos.append((spec, result, folder))
            print(f"Evaluated {spec['name']}: {args.seeds} paired seeds x 3 policies", flush=True)
    with (output / "runs.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    rng = np.random.default_rng(73)
    comparisons = []
    for family in FAMILIES:
        family_rows = [r for r in results if r["family"] == family]
        paired = {}
        for row in family_rows:
            paired.setdefault((row["circuit"], row["seed"]), {})[row["policy"]] = row
        for baseline in ("uniform", "adaptive"):
            # Bootstrap circuit means, not individual seeds: seeds for one graph
            # are repeated measurements, not independent circuit samples.
            by_circuit = {}
            for (circuit, _), policies in paired.items():
                base, learned = policies[baseline]["best_cost"], policies["learned"]["best_cost"]
                by_circuit.setdefault(circuit, []).append(100 * (base-learned) / base if base else 0)
            values = np.array([statistics.mean(v) for v in by_circuit.values()])
            draws = rng.choice(values, size=(2000, len(values)), replace=True).mean(axis=1)
            comparisons.append(dict(family=family, baseline=baseline,
                                    mean_gain_percent=float(values.mean()),
                                    ci95=[float(v) for v in np.quantile(draws, [0.025, 0.975])],
                                    circuits=len(values), paired_runs=len(paired)))
    summary = dict(runs=len(results), train_seconds=training_seconds,
                   training_circuits=len(training_ids), training_samples=len(rows),
                   test_circuits=args.test_circuits * len(FAMILIES), seeds=args.seeds,
                   steps=args.steps, comparisons=comparisons,
                   zero_violations=all(r["violations"] == 0 for r in results),
                   mean_seconds={p: statistics.mean(r["seconds"] for r in results if r["policy"] == p)
                                 for p in ("uniform", "adaptive", "learned")},
                   methodology="Synthetic graphs; frozen model; disjoint test seeds; bias_fanout family held out; equal proposal budgets; circuit-level bootstrap.",
                   python=platform.python_version(), numpy=np.__version__,
                   source_sha256={name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                                  for name in ("analog_layout.py", "placement_learning.py", "benchmark_circuits.py", "benchmark.py")})
    write_json(output / "summary.json", summary)
    render_report(output, summary, demos)
    print(json.dumps(summary, indent=2), flush=True)
    print(f"Report: {(output / 'report.html').resolve()}", flush=True)


def render_report(output, summary, demos):
    table = "".join(f"<tr><td>{html.escape(c['family'])}</td><td>{c['baseline']}</td><td>{c['mean_gain_percent']:.2f}%</td><td>[{c['ci95'][0]:.2f}, {c['ci95'][1]:.2f}]</td></tr>" for c in summary["comparisons"])
    cards = ""
    for spec, result, folder in demos:
        before = (folder / "initial.svg").read_text()
        after = (folder / "optimized.svg").read_text()
        cards += f"<article><h2>{html.escape(spec['family'])}</h2><p>Initial cost {result['initial_cost']:.1f} → learned-policy cost {result['best_cost']:.1f}</p><div class='layouts'><div><h3>Initial</h3>{before}</div><div><h3>Optimized</h3>{after}</div></div></article>"
    document = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Analog placement evaluation</title>
<style>body{{font:16px system-ui;background:#f2f5f9;color:#172536;margin:0}}main{{max-width:1100px;margin:40px auto;padding:24px}}article,.panel{{background:white;padding:24px;border-radius:12px;margin:24px 0}}.layouts{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}svg{{width:100%;max-height:340px}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #ddd}}.tag{{color:#245d88}}@media(max-width:600px){{.layouts{{grid-template-columns:1fr}}}}</style>
<main><p class="tag">REPRODUCIBLE RESEARCH DEMONSTRATOR</p><h1>Learning-assisted analog block placement</h1>
<p>{summary['runs']} optimization runs across {summary['test_circuits']} test circuits. {summary['training_circuits']} separate training circuits. {summary['steps']} proposals per run.</p>
<div class="panel"><h2>What was verified</h2><p>All returned placements satisfy implemented rectangular spacing, boundary, mirror symmetry, and centering constraints. Model weights are frozen during evaluation. One graph family is absent from training.</p>
<p>These are synthetic block graphs with center-terminal wire-length proxies. This benchmark does not demonstrate foundry DRC, LVS, routing, transistor matching, or electrical performance.</p></div>
<div class="panel"><h2>Does learning help?</h2><p>Positive gain means lower wire cost than the baseline. Intervals use bootstrap resampling of circuit averages across paired search seeds. Small samples and synthetic graph families limit generalization.</p>
<table><thead><tr><th>Family</th><th>Baseline</th><th>Mean learned gain</th><th>95% interval (%)</th></tr></thead><tbody>{table}</tbody></table>
<p>Mean seconds per run: {'; '.join(f'{p}: {s:.3f}' for p,s in summary['mean_seconds'].items())}. Training time: {summary['train_seconds']:.1f}s. Comparisons use equal proposal counts, not equal runtime.</p></div>
{cards}<p>Artifacts: <a href="runs.csv">all run metrics</a> · <a href="summary.json">summary and source hashes</a> · <a href="move_policy.json">trained model</a></p></main></html>"""
    (output / "report.html").write_text(document)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/benchmark"))
    parser.add_argument("--train-circuits", type=int, default=8)
    parser.add_argument("--train-steps", type=int, default=3000)
    parser.add_argument("--test-circuits", type=int, default=6)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--steps", type=int, default=6000)
    args = parser.parse_args()
    if min(args.train_circuits, args.train_steps, args.test_circuits, args.seeds, args.steps) <= 0:
        parser.error("All experiment counts must be positive")
    run(args)
