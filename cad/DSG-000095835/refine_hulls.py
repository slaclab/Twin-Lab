"""Trial higher-resolution hulls without modifying the active assembly cache or export."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import math
import os
import resource
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from twin_lab.paths import CACHE_ROOT

HERE = Path(__file__).resolve().parent
ACTIVE_CACHE = CACHE_ROOT / "convex-collision" / "reviews"
DEFAULT_OUTPUT = CACHE_ROOT / "95835-redecomposition"
HOME_CONTACT_REFS = {
    "P1177", "P1180", "P906", "P952", "P1098", "P1097", "P1141", "P1140", "P1054", "P1053",
}


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def audit_record(audit):
    result = asdict(audit)
    result["source"] = str(audit.source)
    return result


def select_targets(baseline):
    return sorted(
        (item for item in baseline if item["max_bulge_mm"] > 2.0
         or item["max_gap_mm"] > 0.2 or item["part_ref"] in HOME_CONTACT_REFS),
        key=lambda item: (-item["max_bulge_mm"], item["source"]),
    )


def best_candidate(baseline, candidates):
    eligible = [
        item for item in candidates
        if item.get("status") == "ok"
        and all(math.isfinite(item["audit"][key]) for key in (
            "max_bulge_mm", "max_gap_mm", "hull_volume_m3", "outside_fraction",
        ))
        and item["audit"]["max_bulge_mm"] < baseline["max_bulge_mm"] * 0.9
        and item["audit"]["outside_fraction"] == 0.0
        and item["audit"]["max_gap_mm"] <= 1e-6
        and item["audit"]["hull_volume_m3"] <= baseline["hull_volume_m3"] * 1.02
        and 0 < item["audit"]["hull_count"] <= 32
    ]
    return min(eligible, key=lambda item: item["audit"]["max_bulge_mm"], default=None)


def candidate_parts(run_dir, sources, recipe_bytes):
    from twin_lab.convex_collision import (
        DecompositionSettings,
        _read_manifest,
        _safe_name,
        _source_digest,
        read_part_refs,
    )
    from twin_lab.hull_audit import audit_cache

    run_dir = run_dir.resolve()
    plan = json.loads((run_dir / "plan.json").read_text())
    state = json.loads((run_dir / "results.json").read_text())
    if state["status"] != "completed":
        raise ValueError("Refinement run has not completed")
    if hashlib.sha256(recipe_bytes).hexdigest() != plan["recipe_sha256"]:
        raise ValueError("Assembly recipe changed since refinement")
    if {str(source) for source in sources} != set(plan["source_sha256"]):
        raise ValueError("Assembly sources differ from the refinement plan")
    targets = {item["source"]: item for item in plan["targets"]}
    parts, evidence = {}, []
    for source in sorted(sources):
        digest = _source_digest(source)
        if digest != plan["source_sha256"][str(source)]:
            raise ValueError(f"Source mesh changed since refinement: {source}")
        baseline = targets.get(str(source))
        best = best_candidate(baseline, state["results"].get(source.stem, [])) if baseline else None
        cache = Path(best["cache"]).resolve() if best else ACTIVE_CACHE / _safe_name(source.stem)
        if best and not cache.is_relative_to(run_dir):
            raise ValueError(f"Candidate cache is outside refinement run: {cache}")
        manifest = cache / "manifest.json"
        payload = json.loads(manifest.read_text())
        if payload["source"] != str(source) or payload["source_sha256"] != digest:
            raise ValueError(f"Hull manifest does not match source: {manifest}")
        resolution = best["resolution"] if best else 50
        loaded = _read_manifest(manifest, source, DecompositionSettings(
            preprocess_resolution=resolution,
        ))
        if (not loaded or {item.part_ref for item in loaded} != set(read_part_refs(source))
                or any(not item.hulls for item in loaded)):
            raise ValueError(f"Missing or stale hulls: {manifest}")
        if best:
            fresh = audit_cache(cache, refresh=True)
            if len(fresh) != 1 or fresh[0].audit.part_ref != baseline["part_ref"]:
                raise ValueError(f"Unexpected candidate audit selections: {cache}")
            checked = {**best, "audit": audit_record(fresh[0].audit)}
            if best_candidate(baseline, [checked]) is None:
                raise ValueError(f"Candidate no longer meets quality gates: {cache}")
            print(f"Re-audited {source.stem}: resolution {resolution}", flush=True)
        parts[source] = loaded
        evidence.append({
            "source": str(source), "source_sha256": digest, "resolution": resolution,
            "improved": best is not None,
            "hulls": {str(hull): hashlib.sha256(hull.read_bytes()).hexdigest()
                      for part in loaded for hull in part.hulls},
        })
    return parts, evidence


def evaluate(source, output, resolution, memory_gb):
    memory_bytes = int(memory_gb * 1024**3)
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    from twin_lab.convex_collision import DecompositionSettings, decompose_source
    from twin_lab.hull_audit import audit_cache
    from twin_lab.hull_inflation import inflate_cache

    cache = output / f"resolution-{resolution}"
    started = time.monotonic()
    parts = decompose_source(source, cache, DecompositionSettings(preprocess_resolution=resolution))
    if len(parts) != 1 or not parts[0].hulls:
        raise ValueError(f"Expected one nonempty reviewed selection in {source}")
    part_cache = parts[0].hulls[0].parent
    raw = audit_record(audit_cache(part_cache)[0].audit)
    inflate_cache(part_cache)
    checked = audit_record(audit_cache(part_cache)[0].audit)
    result = {
        "status": "ok", "resolution": resolution, "cache": str(part_cache),
        "raw_audit": raw, "audit": checked,
        "seconds": time.monotonic() - started,
        "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    }
    write_json(output / f"{source.stem}.{resolution}.json", result)
    print(
        f"{source.stem} res={resolution}: bulge {checked['max_bulge_mm']:.3f} mm, "
        f"gap {checked['max_gap_mm']:.6f} mm, {checked['hull_count']} hulls, "
        f"{result['seconds']:.1f} s, peak {result['peak_rss_mb']:.0f} MB",
        flush=True,
    )


def write_comparison(output, targets, results):
    rows = []
    for baseline in targets:
        source = Path(baseline["source"])
        candidates = results.get(source.stem, [])
        best = best_candidate(baseline, candidates)
        after = best["audit"] if best else baseline
        rows.append({
            "source": source.name, "part_ref": baseline["part_ref"],
            "status": "improved" if best else "no_improvement" if candidates else "pending",
            "resolution": best["resolution"] if best else 50,
            "before_bulge_mm": baseline["max_bulge_mm"],
            "after_bulge_mm": after["max_bulge_mm"],
            "before_gap_mm": baseline["max_gap_mm"], "after_gap_mm": after["max_gap_mm"],
            "before_hulls": baseline["hull_count"], "after_hulls": after["hull_count"],
            "candidate_cache": best["cache"] if best else "",
        })
    temporary = output / "comparison.csv.new"
    with temporary.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(output / "comparison.csv")


def run_batch(args, targets):
    output = args.output
    state_path = output / "results.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"results": {}}
    results = state["results"]
    state.update(status="running", pid=os.getpid())
    write_json(state_path, state)
    environment = {
        **os.environ, "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    }
    for resolution in args.resolutions:
        for baseline in targets:
            source = Path(baseline["source"])
            candidates = results.setdefault(source.stem, [])
            if any(item["resolution"] == resolution for item in candidates):
                continue
            best = best_candidate(baseline, candidates)
            if best and best["audit"]["max_bulge_mm"] <= args.target_mm:
                continue
            if any(item["status"] == "failed" for item in candidates):
                continue
            print(f"Starting {source.stem}, resolution {resolution}", flush=True)
            command = [
                sys.executable, "-u", str(Path(__file__).resolve()),
                "--output", str(output), "--worker-source", str(source),
                "--worker-resolution", str(resolution), "--memory-gb", str(args.memory_gb),
            ]
            result_path = output / f"{source.stem}.{resolution}.json"
            try:
                subprocess.run(command, env=environment, check=True, timeout=args.part_timeout_s)
                result = json.loads(result_path.read_text())
            except (subprocess.SubprocessError, OSError, ValueError) as error:
                result = {"status": "failed", "resolution": resolution, "error": str(error)}
                print(f"Failed {source.stem}: {error}", flush=True)
            candidates.append(result)
            write_json(state_path, state)
            write_comparison(output, targets, results)
    state["status"] = "completed"
    write_json(state_path, state)
    write_comparison(output, targets, results)
    improved = sum(bool(best_candidate(item, results.get(Path(item["source"]).stem, [])))
                   for item in targets)
    print(f"Completed: {improved}/{len(targets)} selections improved. Active model unchanged.",
          flush=True)
    print(f"Comparison: {output / 'comparison.csv'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--resolutions", type=int, nargs="+", default=[200, 400, 800])
    parser.add_argument("--target-mm", type=float, default=0.5)
    parser.add_argument("--memory-gb", type=float, default=10.0)
    parser.add_argument("--part-timeout-s", type=float, default=1800.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--worker-source", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-resolution", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if (not all(value > 50 for value in args.resolutions)
            or args.resolutions != sorted(set(args.resolutions))
            or not all(math.isfinite(value) and value > 0 for value in (
                args.target_mm, args.memory_gb, args.part_timeout_s,
            ))):
        parser.error("Use ascending unique resolutions above 50 and positive finite limits")
    if args.worker_source is not None:
        if args.worker_resolution is None or args.worker_resolution <= 50:
            parser.error("Worker resolution must be above 50")
        evaluate(args.worker_source, args.output, args.worker_resolution, args.memory_gb)
        return
    from twin_lab.convex_collision import _source_digest
    from twin_lab.hull_audit import audit_cache

    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "run.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("A refinement job is already using this output directory")
        manifests = [json.loads(path.read_text()) for path in ACTIVE_CACHE.rglob("manifest.json")]
        source_root = (CACHE_ROOT / "DSG-000095835" / "meshes").resolve()
        if not manifests or any(Path(item["source"]).parent != source_root for item in manifests):
            parser.error("Active cache must contain only DSG-000095835 source selections")
        if any(_source_digest(Path(item["source"])) != item["source_sha256"] for item in manifests):
            parser.error("Active decompositions are stale; rebuild before refining")
        baseline = [audit_record(part.audit) for part in audit_cache(ACTIVE_CACHE)]
        targets = select_targets(baseline)
        if not targets:
            parser.error("No selections need targeted refinement")
        plan = {
            "schema": 1, "resolutions": args.resolutions, "target_mm": args.target_mm,
            "memory_gb": args.memory_gb, "part_timeout_s": args.part_timeout_s,
            "recipe_sha256": hashlib.sha256(
                (HERE / "reviews/assembly.yaml").read_bytes()
            ).hexdigest(),
            "source_sha256": {item["source"]: item["source_sha256"] for item in manifests},
            "targets": targets,
        }
        print(
            f"Selected {len(targets)}/{len(baseline)} selections; "
            f"resolutions {args.resolutions}; target bulge {args.target_mm} mm",
            flush=True,
        )
        print(f"One worker, two native threads, {args.memory_gb:g} GB address-space limit, "
              f"{args.part_timeout_s:g} s per attempt", flush=True)
        if args.dry_run:
            for item in targets:
                print(f"  {Path(item['source']).stem}: bulge {item['max_bulge_mm']:.3f} mm, "
                      f"gap {item['max_gap_mm']:.3f} mm")
            return
        plan_path = args.output / "plan.json"
        if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
            parser.error("Inputs or settings changed; use a new output directory")
        write_json(plan_path, plan)
        run_batch(args, targets)


if __name__ == "__main__":
    main()