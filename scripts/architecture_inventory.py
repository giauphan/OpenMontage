#!/usr/bin/env python3
"""OpenMontage Architecture Baseline and Inventory Generator.

Generates:
1. architecture-inventory.json (LOC, AST classes/functions, complexity, hotspots)
2. contract-inventory.json (Tools, capabilities, registry names, schemas, pipeline refs)
3. reachability-inventory.json (Reachability classification: ACTIVE, UNKNOWN, CANDIDATE)
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


ROOT_DIR = Path(__file__).resolve().parent.parent

GENERATED_INVENTORIES = {
    "architecture-inventory.json",
    "contract-inventory.json",
    "reachability-inventory.json",
}


def get_git_tracked_files() -> List[str]:
    """Get list of files tracked by git, excluding generated inventory files."""
    res = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        line.strip()
        for line in res.stdout.splitlines()
        if line.strip() and line.strip() not in GENERATED_INVENTORIES
    ]


def calculate_complexity(node: ast.AST) -> int:
    """Approximate cyclomatic complexity from an AST node."""
    complexity = 1
    for child in ast.walk(node):
        if isinstance(
            child,
            (
                ast.If,
                ast.While,
                ast.For,
                ast.AsyncFor,
                ast.ExceptHandler,
                ast.With,
                ast.AsyncWith,
                ast.Assert,
            ),
        ):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += len(child.values) - 1
    return complexity


def analyze_python_file(file_path: Path) -> Dict[str, Any]:
    """Analyze AST and lines of code for a Python file."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"error": str(exc)}

    lines = content.splitlines()
    physical_loc = len(lines)
    blank_lines = sum(1 for line in lines if not line.strip())
    comment_lines = sum(1 for line in lines if line.strip().startswith("#"))
    logical_loc = physical_loc - blank_lines - comment_lines

    classes = []
    functions = []
    complexity = 1

    try:
        tree = ast.parse(content, filename=str(file_path))
        complexity = calculate_complexity(tree)

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_loc = (node.end_lineno or node.lineno) - node.lineno + 1
                functions.append({
                    "name": node.name,
                    "lineno": node.lineno,
                    "loc": func_loc,
                    "complexity": calculate_complexity(node),
                })
            elif isinstance(node, ast.ClassDef):
                cls_loc = (node.end_lineno or node.lineno) - node.lineno + 1
                methods = []
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append({
                            "name": sub.name,
                            "lineno": sub.lineno,
                            "loc": (sub.end_lineno or sub.lineno) - sub.lineno + 1,
                            "complexity": calculate_complexity(sub),
                        })
                classes.append({
                    "name": node.name,
                    "lineno": node.lineno,
                    "loc": cls_loc,
                    "methods": methods,
                    "complexity": calculate_complexity(node),
                })
    except SyntaxError as e:
        return {
            "physical_loc": physical_loc,
            "logical_loc": logical_loc,
            "bytes": len(content.encode("utf-8")),
            "classes": [],
            "functions": [],
            "complexity": 1,
            "parse_error": str(e),
        }

    return {
        "physical_loc": physical_loc,
        "logical_loc": logical_loc,
        "bytes": len(content.encode("utf-8")),
        "classes": classes,
        "functions": functions,
        "complexity": complexity,
    }


def analyze_other_file(file_path: Path) -> Dict[str, Any]:
    """Basic line and byte counting for non-Python files."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        physical_loc = len(lines)
        blank_lines = sum(1 for line in lines if not line.strip())
        return {
            "physical_loc": physical_loc,
            "logical_loc": physical_loc - blank_lines,
            "bytes": len(content.encode("utf-8")),
        }
    except Exception:
        return {
            "physical_loc": 0,
            "logical_loc": 0,
            "bytes": file_path.stat().st_size if file_path.exists() else 0,
        }


def extract_imports(file_path: Path) -> Set[str]:
    """Extract static import module names from a Python file."""
    imports = set()
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(content, filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
    except Exception:
        pass
    return imports


def inventory_tools_and_registry() -> Dict[str, Any]:
    """Discover tools via registry and inspect their contracts."""
    try:
        # Import registry from current repo
        if str(ROOT_DIR) not in sys.path:
            sys.path.insert(0, str(ROOT_DIR))
        from tools.tool_registry import registry
        registry.discover()

        tools_data = {}
        for name, tool in registry._tools.items():
            info = {}
            if hasattr(tool, "get_info"):
                try:
                    info = tool.get_info()
                except Exception as e:
                    info = {"error": str(e)}

            module_name = tool.__class__.__module__
            class_name = tool.__class__.__name__

            tools_data[name] = {
                "name": getattr(tool, "name", name),
                "version": getattr(tool, "version", "unknown"),
                "capability": getattr(tool, "capability", "unknown"),
                "provider": getattr(tool, "provider", "unknown"),
                "tier": str(getattr(tool, "tier", "unknown")),
                "status": str(getattr(tool, "status", "unknown")),
                "module": module_name,
                "class_name": class_name,
                "dependencies": getattr(tool, "dependencies", []),
                "supports": getattr(tool, "supports", {}) if isinstance(getattr(tool, "supports", {}), dict) else {},
                "input_schema": getattr(tool, "input_schema", {}),
                "output_schema": getattr(tool, "output_schema", {}),
                "fallback_tools": getattr(tool, "fallback_tools", []),
                "agent_skills": getattr(tool, "agent_skills", []),
                "render_engines": info.get("render_engines", []),
            }
        return tools_data
    except Exception as exc:
        return {"discovery_error": str(exc)}


def inventory_pipelines() -> Dict[str, Any]:
    """Inventory all YAML pipelines in pipeline_defs/."""
    pipeline_dir = ROOT_DIR / "pipeline_defs"
    pipelines = {}
    if not pipeline_dir.is_dir():
        return pipelines

    import yaml
    for f in sorted(pipeline_dir.glob("*.yaml")):
        try:
            with open(f, "r", encoding="utf-8") as yf:
                data = yaml.safe_load(yf) or {}
                raw_stages = data.get("stages") or []
                if isinstance(raw_stages, dict):
                    stage_defs = [{"name": k, **v} for k, v in raw_stages.items() if isinstance(v, dict)]
                elif isinstance(raw_stages, list):
                    stage_defs = [s for s in raw_stages if isinstance(s, dict)]
                else:
                    stage_defs = []

                pipelines[f.stem] = {
                    "file": str(f.relative_to(ROOT_DIR)),
                    "name": data.get("name", f.stem),
                    "stages": [s.get("name") for s in stage_defs if s.get("name")],
                    "tools_referenced": [],
                }
                # Collect tool references
                tools_ref = set()
                ref_input = data.get("reference_input") or {}
                if isinstance(ref_input, dict):
                    for tool in ref_input.get("analysis_tools", []):
                        if isinstance(tool, str):
                            tools_ref.add(tool)

                for stage_def in stage_defs:
                    for key in ("tools_available", "required_tools", "fallback_tools"):
                        for tool in stage_def.get(key, []) or []:
                            if isinstance(tool, str):
                                tools_ref.add(tool)
                pipelines[f.stem]["tools_referenced"] = sorted(tools_ref)
        except Exception as e:
            pipelines[f.stem] = {"file": str(f.relative_to(ROOT_DIR)), "error": str(e)}

    return pipelines


def build_reachability_report(
    tracked_files: List[str],
    tools: Dict[str, Any],
    pipelines: Dict[str, Any],
) -> Dict[str, Any]:
    """Determine reachability classification: ACTIVE, UNKNOWN, CANDIDATE."""
    # Collect all static imports across python files
    all_imports = set()
    file_imports: Dict[str, Set[str]] = {}
    py_files = [f for f in tracked_files if f.endswith(".py")]

    for pf in py_files:
        full_p = ROOT_DIR / pf
        imps = extract_imports(full_p)
        file_imports[pf] = imps
        all_imports.update(imps)

    # Tool modules
    tool_modules = set()
    for t_name, t_meta in tools.items():
        if isinstance(t_meta, dict) and "module" in t_meta:
            tool_modules.add(t_meta["module"])

    # Collect tool names referenced across pipelines
    pipeline_tool_refs = set()
    for p_info in pipelines.values():
        if isinstance(p_info, dict):
            for t in p_info.get("tools_referenced", []):
                pipeline_tool_refs.add(t)

    # Collect string mentions in scripts, yaml, md
    content_corpus = []
    for f in tracked_files:
        if f.endswith((".yaml", ".yml", ".md", ".json", ".sh", ".js", ".ts", ".tsx")):
            try:
                content_corpus.append((f, (ROOT_DIR / f).read_text(encoding="utf-8", errors="ignore")))
            except Exception:
                pass

    reachability = {}
    for f in tracked_files:
        status = "UNKNOWN"
        reasons = []

        # If it's a test
        if f.startswith("tests/"):
            status = "ACTIVE"
            reasons.append("test file")
        # If it's a doc, workflow, schema, skill, or core configuration
        elif f.startswith((".agents/", ".github/", "docs/", "schemas/", "pipeline_defs/", "styles/")) or f in (
            "README.md",
            "AGENTS.md",
            "AGENT_GUIDE.md",
            "CLAUDE.md",
            "package.json",
            "package-lock.json",
            "pyproject.toml",
            "requirements.txt",
            "Dockerfile",
            "docker-compose.yml",
            ".gitignore",
            "Makefile",
            "tsconfig.json",
        ):
            status = "ACTIVE"
            reasons.append("project configuration / documentation / workflow / skill")
        elif f.startswith("remotion-composer/"):
            status = "ACTIVE"
            reasons.append("remotion-composer component/asset")
        elif f.startswith("backlot/"):
            status = "ACTIVE"
            reasons.append("backlot board component/asset")
        elif f.endswith(".py"):
            mod_path = f[:-3].replace("/", ".")
            stem = Path(f).stem
            if mod_path in all_imports:
                status = "ACTIVE"
                reasons.append("statically imported")
            elif mod_path in tool_modules:
                status = "ACTIVE"
                reasons.append("registered tool module in ToolRegistry")
            elif stem in pipeline_tool_refs:
                status = "ACTIVE"
                reasons.append("referenced in pipeline definition")
            elif any(f in corpus_text or stem in corpus_text for c_file, corpus_text in content_corpus if c_file != f):
                status = "ACTIVE"
                reasons.append("referenced in config/docs/scripts")
            else:
                status = "UNKNOWN"
                reasons.append("unresolved python source file without static import or recorded reference")
        else:
            stem = Path(f).name
            if any(f in corpus_text or stem in corpus_text for c_file, corpus_text in content_corpus if c_file != f):
                status = "ACTIVE"
                reasons.append("referenced static asset or configuration")
            else:
                status = "UNKNOWN"
                reasons.append("static asset or configuration without recorded reference")

        reachability[f] = {
            "status": status,
            "reasons": reasons,
        }

    return reachability


def main():
    print("=" * 70)
    print("OpenMontage Architecture Baseline and Inventory Generator")
    print("=" * 70)

    # 1. Git metadata
    tracked_files = get_git_tracked_files()
    git_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT_DIR, capture_output=True, text=True
    ).stdout.strip()
    git_status = subprocess.run(
        ["git", "status", "--short"], cwd=ROOT_DIR, capture_output=True, text=True
    ).stdout.strip()

    print(f"Commit HEAD: {git_head}")
    print(f"Tracked files: {len(tracked_files)}")

    # 2. File and AST analysis
    inventory_by_file = {}
    hotspots = []

    for rel_path in tracked_files:
        full_path = ROOT_DIR / rel_path
        if not full_path.is_file():
            continue

        ext = full_path.suffix.lower()
        if ext == ".py":
            data = analyze_python_file(full_path)
            data["language"] = "python"
        elif ext in (".ts", ".tsx", ".js", ".jsx", ".mjs"):
            data = analyze_other_file(full_path)
            data["language"] = "javascript/typescript"
        elif ext in (".yaml", ".yml"):
            data = analyze_other_file(full_path)
            data["language"] = "yaml"
        elif ext == ".md":
            data = analyze_other_file(full_path)
            data["language"] = "markdown"
        elif ext == ".json":
            data = analyze_other_file(full_path)
            data["language"] = "json"
        else:
            data = analyze_other_file(full_path)
            data["language"] = "other"

        inventory_by_file[rel_path] = data

        # Track hotspots in python / ts
        loc = data.get("physical_loc", 0)
        cplx = data.get("complexity", 1)
        if loc >= 300 and data.get("language") in ("python", "javascript/typescript"):
            hotspots.append({
                "path": rel_path,
                "physical_loc": loc,
                "logical_loc": data.get("logical_loc", 0),
                "complexity": cplx,
                "classes": len(data.get("classes", [])),
                "functions": len(data.get("functions", [])),
            })

    # Sort hotspots by physical_loc descending
    hotspots.sort(key=lambda x: x["physical_loc"], reverse=True)

    # 3. Tool and Registry Discovery
    print("Discovering tools via registry...")
    tools_data = inventory_tools_and_registry()
    print(f"Discovered tools: {len(tools_data)}")

    # 4. Pipelines
    pipelines_data = inventory_pipelines()
    print(f"Discovered pipelines: {len(pipelines_data)}")

    # 5. Reachability Analysis
    reachability_data = build_reachability_report(tracked_files, tools_data, pipelines_data)

    # Write output files
    # Write output files (deterministic without run-specific commit or python build strings)
    arch_output = {
        "metadata": {
            "tracked_files_count": len(tracked_files),
        },
        "hotspots": hotspots[:30],
        "files": inventory_by_file,
    }

    contract_output = {
        "metadata": {
            "tool_count": len(tools_data),
            "pipeline_count": len(pipelines_data),
        },
        "tools": tools_data,
        "pipelines": pipelines_data,
    }

    reachability_output = {
        "metadata": {
            "total_files": len(reachability_data),
            "unknown_count": sum(1 for v in reachability_data.values() if v["status"] == "UNKNOWN"),
            "active_count": sum(1 for v in reachability_data.values() if v["status"] == "ACTIVE"),
        },
        "reachability": reachability_data,
    }

    arch_file = ROOT_DIR / "architecture-inventory.json"
    contract_file = ROOT_DIR / "contract-inventory.json"
    reach_file = ROOT_DIR / "reachability-inventory.json"

    with open(arch_file, "w", encoding="utf-8") as f:
        json.dump(arch_output, f, indent=2)
    print(f"Written: {arch_file.relative_to(ROOT_DIR)} ({arch_file.stat().st_size} bytes)")

    with open(contract_file, "w", encoding="utf-8") as f:
        json.dump(contract_output, f, indent=2)
    print(f"Written: {contract_file.relative_to(ROOT_DIR)} ({contract_file.stat().st_size} bytes)")

    with open(reach_file, "w", encoding="utf-8") as f:
        json.dump(reachability_output, f, indent=2)
    print(f"Written: {reach_file.relative_to(ROOT_DIR)} ({reach_file.stat().st_size} bytes)")

    print("\n--- TOP HOTSPOTS ---")
    for h in hotspots[:10]:
        print(f"  {h['physical_loc']:5d} LOC (complexity: {h['complexity']:3d}) - {h['path']}")

    print("\nBaseline inventory generated successfully.")


if __name__ == "__main__":
    main()
