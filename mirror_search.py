"""Bayesian search of independently verified SKY130 current-mirror layouts.

Every queried design is generated, checked by DRC/LVS, and characterized with
capacitance-extracted PDK simulations. A random-search comparison uses the same
initial designs and oracle-call budget. No superiority is assumed in advance.
"""
import argparse
import hashlib
import itertools
import json
import math
import os
import time
from pathlib import Path

import numpy as np
from scipy.special import ndtr

from physical_flow import ROOT, PDK_BUILD, generate, simulate, verify


def expected_improvement(x, observed, scores):
    """Fixed-kernel Gaussian process with a standardized scalar objective."""
    y = np.array(scores, dtype=float)
    mean, scale = y.mean(), max(y.std(), 1e-6)
    z = (y-mean) / scale
    kernel = lambda a, b: np.exp(-0.5 * np.sum(((a[:, None]-b[None, :]) / 0.45)**2, axis=2))
    k = kernel(observed, observed) + np.eye(len(y)) * 1e-5
    cross = kernel(x, observed)
    inverse_y = np.linalg.solve(k, z)
    predicted = cross @ inverse_y
    variance = np.maximum(1e-10, 1 - np.sum(cross * np.linalg.solve(k, cross.T).T, axis=1))
    sigma = np.sqrt(variance)
    improvement = z.min() - predicted - 0.01
    normalized = improvement / sigma
    acquisition = improvement * ndtr(normalized) + sigma * np.exp(-normalized**2/2) / math.sqrt(2*math.pi)
    return acquisition, predicted * scale + mean, sigma * scale


def evaluate(config, spec, folder, pdk):
    folder.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    width, length, columns = config
    _, geometry = generate(width, length, int(columns), folder)
    verification = verify(folder, pdk)
    electrical = []
    if verification["drc_pass"] and verification["lvs_pass"]:
        netlist = (folder / "extracted_capacitance.spice").read_text()
        for corner in spec["corners"]:
            for temperature in spec["temperatures_c"]:
                metrics = simulate(netlist, folder / f"{corner}-{temperature}", pdk, corner, temperature,
                                   reference_ua=spec["reference_current_ua"])
                electrical.append(metrics)
    if electrical:
        error = max(m["worst_error_percent_0p6_to_1p6v"] for m in electrical)
        vref = max(m["max_reference_voltage_v"] for m in electrical)
        # A missing crossing implies no 3dB crossing within the 10GHz scan.
        bandwidth = min(m["bandwidth_3db_hz"] or 1e10 for m in electrical)
        penalty = (max(0, error/spec["max_copy_error_percent"]-1) +
                   max(0, vref/spec["max_reference_voltage_v"]-1) +
                   max(0, spec["minimum_bandwidth_hz"]/bandwidth-1))
        feasible = penalty == 0
        score = math.log(geometry["area_um2"]) + 10*penalty
    else:
        error = vref = bandwidth = None
        feasible, score = False, 100.0
    result = dict(config=list(config), geometry=geometry, verification=verification,
                  worst_error_percent=error, worst_reference_voltage_v=vref,
                  minimum_bandwidth_hz=bandwidth, feasible=feasible, score=score,
                  electrical=electrical, seconds=time.perf_counter()-started)
    (folder / "evaluation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"Evaluated W={width} L={length} cols={columns}: feasible={feasible}, area={geometry['area_um2']:.2f}, error={error}", flush=True)
    return result


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_hashes = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                     for name in ("mirror_search.py", "physical_flow.py")}
    pdk_root = args.pdk_root.resolve()
    pdk = pdk_root / "sky130A"
    os.environ.update(PDK_ROOT=str(pdk_root), PDKPATH=str(pdk))
    spec = json.loads(args.spec.read_text())
    # The current characterization API explicitly covers this range.
    if spec["output_voltage_range_v"] != [0.6, 1.6]:
        raise ValueError("This demonstrator characterizes the fixed 0.6–1.6V output range")
    (output / "specification.json").write_text(json.dumps(spec, indent=2) + "\n")
    candidates = list(itertools.product(spec["width_candidates_um"], spec["length_candidates_um"], spec["column_candidates"]))
    if not 4 <= args.budget <= len(candidates):
        raise ValueError("Budget must be between four and the candidate count")
    x = np.asarray(candidates, dtype=float)
    x = (x-x.min(axis=0)) / np.maximum(x.max(axis=0)-x.min(axis=0), 1)
    cache, experiments = {}, []
    spec_hash = hashlib.sha256(args.spec.read_bytes()).hexdigest()
    for seed in range(args.seed_offset, args.seed_offset + args.seeds):
        initial = np.random.default_rng(seed).choice(len(candidates), size=4, replace=False).tolist()
        for strategy in ("bayesian", "random"):
            rng = np.random.default_rng(seed + 100)
            selected, scores, trace = [], [], []
            for iteration in range(args.budget):
                prediction = None
                if iteration < len(initial):
                    index = initial[iteration]
                else:
                    remaining = [i for i in range(len(candidates)) if i not in selected]
                    if strategy == "random":
                        index = int(rng.choice(remaining))
                    else:
                        acquisition, predicted, uncertainty = expected_improvement(x[remaining], x[selected], scores)
                        offset = int(np.argmax(acquisition))
                        index = remaining[offset]
                        prediction = dict(predicted_score=float(predicted[offset]),
                                          uncertainty=float(uncertainty[offset]),
                                          expected_improvement=float(acquisition[offset]))
                if index not in cache:
                    folder = output / "designs" / f"candidate-{index:03d}"
                    # No cache is read from previous experiments: avoid silently
                    # reusing designs generated with different source or rules.
                    cache[index] = evaluate(candidates[index], spec, folder, pdk)
                result = cache[index]
                selected.append(index)
                scores.append(result["score"])
                feasible = [i for i in selected if cache[i]["feasible"]]
                best = min(feasible, key=lambda i: cache[i]["geometry"]["area_um2"]) if feasible else None
                trace.append(dict(iteration=iteration+1, candidate=index, config=list(candidates[index]),
                                  feasible=result["feasible"], score=result["score"], prediction=prediction,
                                  best_feasible_candidate=best,
                                  best_feasible_area_um2=cache[best]["geometry"]["area_um2"] if best is not None else None))
                print(f"seed={seed} strategy={strategy} call={iteration+1} best={best}", flush=True)
            record = dict(seed=seed, strategy=strategy, budget=args.budget, trace=trace)
            experiments.append(record)
            (output / f"{strategy}-seed-{seed}.json").write_text(json.dumps(record, indent=2) + "\n")
    if args.exhaustive:
        for index, candidate in enumerate(candidates):
            if index not in cache:
                cache[index] = evaluate(candidate, spec, output / "designs" / f"candidate-{index:03d}", pdk)
    feasible = [i for i,r in cache.items() if r["feasible"]]
    best = min(feasible, key=lambda i: cache[i]["geometry"]["area_um2"]) if feasible else None
    summary = dict(pdk_build=PDK_BUILD, candidates=len(candidates), unique_evaluations=len(cache),
                   feasible_evaluations=len(feasible), best_candidate=best,
                   best_design=cache[best] if best is not None else None,
                   specification_sha256=spec_hash, experiments=experiments,
                   source_sha256=source_hashes,
                   exhaustive_grid_check=args.exhaustive,
                   strategy_summary={strategy: dict(
                       trials=args.seeds,
                       successful_trials=sum(e['trace'][-1]['best_feasible_candidate'] is not None for e in experiments if e['strategy']==strategy),
                       median_feasible_area_um2=float(np.median([e['trace'][-1]['best_feasible_area_um2'] for e in experiments if e['strategy']==strategy and e['trace'][-1]['best_feasible_area_um2'] is not None])) if any(e['trace'][-1]['best_feasible_candidate'] is not None for e in experiments if e['strategy']==strategy) else None)
                       for strategy in ('bayesian','random')},
                   surrogate=dict(type="Gaussian process", kernel="RBF", length_scale=0.45,
                                  diagonal_noise=1e-5, objective="log(area) + 10*sum(normalized constraint excesses)",
                                  acquisition="Expected improvement; exploration margin 0.01; four shared initial observations"),
                   methodology="Paired shared initialization; equal oracle-call budgets; cache shared only to save computation; capacitance-only extraction; discrete single-circuit search; no assumed AI advantage.")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k:v for k,v in summary.items() if k not in ('experiments','best_design')}, indent=2), flush=True)
    if best is None:
        raise RuntimeError("No physically verified candidate met the electrical specification")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=ROOT / "examples/mirror_spec.json")
    parser.add_argument("--pdk-root", type=Path, default=ROOT / "pdks")
    parser.add_argument("--output", type=Path, default=ROOT / "results/mirror-search")
    parser.add_argument("--budget", type=int, default=12)
    parser.add_argument("--seeds", type=int, default=2)
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--exhaustive", action="store_true", help="Audit all discrete candidates after the paired searches")
    args = parser.parse_args()
    if args.seeds <= 0:
        parser.error("--seeds must be positive")
    run(args)
