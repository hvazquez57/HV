"""Immutable run snapshots, explicit cache integrity, and reproducibility metadata."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

SCHEMA_VERSION = 1
ARTIFACTS = (
    "report.html", "analysis.json", "portfolio_comparison.csv", "allocations.csv",
    "etf_history.csv", "adjusted_prices.csv", "unadjusted_closes.csv",
)
INPUT_FILES = ("adjusted_prices.csv", "unadjusted_closes.csv")
SOURCE_FILES = ("analyze_etfs.py", "market_data.py", "report_store.py")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def price_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(
        index_label="date", float_format="%.17g", lineterminator="\n",
    ).encode("utf-8")


def git_metadata(project: Path) -> dict:
    executable = shutil.which("git")
    if executable is None and sys.platform == "win32":
        import winreg

        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, r"Software\GitForWindows") as key:
                    installed, _ = winreg.QueryValueEx(key, "InstallPath")
                candidate = Path(installed) / "cmd" / "git.exe"
                if candidate.is_file():
                    executable = str(candidate)
                    break
            except OSError:
                continue
    if executable is None:
        return {"commit": None, "dirty": None, "available": False}
    try:
        revision = subprocess.run(
            [executable, "-C", str(project), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        status = subprocess.run(
            [executable, "-C", str(project), "status", "--porcelain", "--untracked-files=normal"],
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout
        return {"commit": revision, "dirty": bool(status.strip()), "available": True}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None, "available": False}


def dependency_versions() -> dict:
    return {
        distribution.metadata["Name"]: distribution.version
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    }


def environment_metadata(project: Path) -> dict:
    versions = dependency_versions()
    constraints = project / "constraints-windows-py313.txt"
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "dependencies": dict(sorted(versions.items(), key=lambda item: item[0].lower())),
        "source_code_sha256": {
            name: sha256((project / name).read_bytes()) for name in SOURCE_FILES
        },
        "constraints_sha256": sha256(constraints.read_bytes()) if constraints.is_file() else None,
        "git": git_metadata(project),
    }


def publish_run(
    result: dict,
    adjusted: pd.DataFrame,
    close: pd.DataFrame,
    output: Path,
    render,
    project: Path,
) -> Path:
    """Expose a complete run and then its pointer, never partially overwrite a run."""
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:12]
    output.mkdir(parents=True, exist_ok=True)
    staging = output / (".pending-" + run_id)
    final = output / run_id
    pointer_temp = output / (".latest-" + run_id + ".tmp")
    published = False
    staging.mkdir()
    try:
        inputs = dict(zip(INPUT_FILES, (price_bytes(adjusted), price_bytes(close))))
        metadata = dict(result["reproducibility"])
        metadata.update({
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "input_sha256": {name: sha256(data) for name, data in inputs.items()},
            "environment": environment_metadata(project),
        })
        result["reproducibility"] = metadata
        for name, data in inputs.items():
            (staging / name).write_bytes(data)
        render(result, staging)
        # Verify the renderer actually created every required artifact before publishing.
        for name in ARTIFACTS:
            if not (staging / name).is_file() or not (staging / name).stat().st_size:
                raise ValueError(f"Cannot publish an incomplete report: {name}.")
        manifest = {
            **metadata,
            "status": "complete",
            "generated_utc": result["generated_utc"],
            "latest_price_date": result["latest_price_date"],
            "artifacts": {name: sha256((staging / name).read_bytes()) for name in ARTIFACTS},
        }
        (staging / "manifest.json").write_bytes(json_bytes(manifest))
        pointer_temp.write_bytes(json_bytes({
            "schema_version": SCHEMA_VERSION, "run_id": run_id,
            "report": f"{run_id}/report.html", "manifest": f"{run_id}/manifest.json",
        }))
        # Both directories are on the same filesystem; final is unique and never reused.
        staging.rename(final)
        published = True
        os.replace(pointer_temp, output / "latest.json")
        return final / "report.html"
    except Exception:
        # Delete only private paths made by this invocation, never earlier runs.
        shutil.rmtree(final if published else staging, ignore_errors=True)
        pointer_temp.unlink(missing_ok=True)
        raise


@dataclass
class CachedSnapshot:
    adjusted: pd.DataFrame
    close: pd.DataFrame
    manifest: dict


def load_snapshot(directory: Path) -> CachedSnapshot:
    directory = directory.expanduser().resolve()
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(
            "Cache requires a completed run directory with manifest.json. "
            "Legacy reports have no verified manifest; generate a new live run first."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("status") != "complete"
        or manifest.get("data_kind") != "live"
        or manifest.get("mode") not in {"live", "cached"}
    ):
        raise ValueError("Cache is incomplete, unsupported, or synthetic; only market snapshots qualify.")
    required = {
        "analysis_cutoff", "requested_start", "settings", "model", "input_sha256",
        "environment", "artifacts", "run_id", "latest_price_date", "source_snapshot",
        "mode", "data_kind", "calendar", "schema_version",
    }
    if not required.issubset(manifest):
        raise ValueError("Cache manifest lacks required provenance fields.")
    if not isinstance(manifest["artifacts"], dict) or not isinstance(manifest["input_sha256"], dict):
        raise ValueError("Cache manifest hashes must be mappings.")
    if (
        not isinstance(manifest["environment"], dict)
        or not isinstance(manifest["environment"].get("source_code_sha256"), dict)
        or not isinstance(manifest["environment"].get("dependencies"), dict)
        or not isinstance(manifest["run_id"], str)
        or not manifest["run_id"]
        or (
            manifest["source_snapshot"] is not None
            and (
                not isinstance(manifest["source_snapshot"], dict)
                or not {"run_id", "manifest_sha256", "origin_run_id"}.issubset(manifest["source_snapshot"])
            )
        )
    ):
        raise ValueError("Cache contains malformed environment or source provenance.")
    for name in ARTIFACTS:
        file = directory / name
        if (
            not file.is_file() or file.stat().st_size == 0
            or sha256(file.read_bytes()) != manifest["artifacts"].get(name)
        ):
            raise ValueError(f"Cache integrity check failed: {name}.")
    for name in INPUT_FILES:
        if manifest["input_sha256"].get(name) != manifest["artifacts"].get(name):
            raise ValueError(f"Cache input hash disagrees with artifact hash: {name}.")
    analysis = json.loads((directory / "analysis.json").read_text(encoding="utf-8"))
    if not isinstance(analysis, dict):
        raise ValueError("Cache analysis must be a JSON object.")
    provenance = analysis.get("reproducibility")
    if not isinstance(provenance, dict) or any(
        provenance.get(key) != manifest[key]
        for key in required - {"artifacts", "latest_price_date"}
    ):
        raise ValueError("Cache manifest and analysis provenance disagree.")
    if analysis.get("latest_price_date") != manifest["latest_price_date"]:
        raise ValueError("Cache manifest and analysis price dates disagree.")
    if not isinstance(manifest["settings"], dict) or set(manifest["settings"]) != {
        "amount", "years", "simulations", "seed", "demo_seed", "block_months",
    }:
        raise ValueError("Cache has invalid analysis settings.")
    frames = [
        pd.read_csv(directory / name, index_col="date", parse_dates=True, float_precision="round_trip")
        for name in INPUT_FILES
    ]
    return CachedSnapshot(frames[0], frames[1], manifest)
