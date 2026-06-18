#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
MoleditPy Workspace Test Runner
Runs tests for all plugins and the main application in DEV_MAIN.
"""

import os
import sys
import subprocess
import time

def run_tests() -> None:
    workspace_dir = os.path.abspath(os.path.dirname(__file__))
    
    # Environment variables to resolve Windows Qt DLL collisions (PySide6 vs PyQt6)
    env = os.environ.copy()
    env["MOLEDITPY_HEADLESS"] = "1"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTEST_QT_API"] = "pyqt6"
    
    # Find all subdirectories with a tests folder
    subdirs = []
    for item in sorted(os.listdir(workspace_dir)):
        item_path = os.path.join(workspace_dir, item)
        if os.path.isdir(item_path) and os.path.isdir(os.path.join(item_path, "tests")):
            subdirs.append(item)
            
    if not subdirs:
        print("No test directories found.")
        return

    print("=" * 60)
    print("      MOLEDITPY WORKSPACE TEST RUNNER")
    print("=" * 60)
    print(f"Found {len(subdirs)} test suites to run.\n")

    results = {}
    
    for i, subdir in enumerate(subdirs, 1):
        subdir_path = os.path.join(workspace_dir, subdir)
        print(f"[{i}/{len(subdirs)}] Running tests in {subdir}...")
        
        # Decide the command to run
        if subdir == "python_molecular_editor":
            # The main app has a specialized test runner
            cmd = [sys.executable, os.path.join("tests", "run_all_tests.py"), "--headless", "--no-cov", "--no-report"]
        else:
            cmd = [sys.executable, "-m", "pytest", "tests/", "-v"]
            
        start_time = time.time()
        
        try:
            result = subprocess.run(
                cmd,
                cwd=subdir_path,
                env=env,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=300  # 5 minute limit per suite
            )
            elapsed = time.time() - start_time
            
            if result.returncode == 0:
                print(f"  -> PASSED ({elapsed:.2f}s)")
                results[subdir] = ("PASSED", elapsed, "")
            else:
                print(f"  -> FAILED ({elapsed:.2f}s)")
                # Show trailing lines of stdout/stderr for quick debugging
                output = (result.stdout or "") + "\n" + (result.stderr or "")
                lines = output.splitlines()
                summary = "\n".join(lines[-20:]) if len(lines) > 20 else output
                results[subdir] = ("FAILED", elapsed, summary)
                
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            print(f"  -> TIMEOUT ({elapsed:.2f}s)")
            results[subdir] = ("TIMEOUT", elapsed, "")
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"  -> ERROR ({e})")
            results[subdir] = ("ERROR", elapsed, str(e))
            
    print("\n" + "=" * 60)
    print("             TEST RUN SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for subdir in subdirs:
        status, elapsed, _ = results.get(subdir, ("UNKNOWN", 0.0, ""))
        print(f" {subdir:<50} : {status} ({elapsed:.1f}s)")
        if status != "PASSED":
            all_passed = False
            
    print("=" * 60)
    
    # Print fail details if any
    for subdir, (status, _, detail) in results.items():
        if status not in ("PASSED", "UNKNOWN") and detail:
            print(f"\n--- Failure Detail for {subdir} ---")
            print(detail)
            print("-" * 60)
            
    if all_passed:
        print("\nSUCCESS: All workspace test suites passed successfully!")
        sys.exit(0)
    else:
        print("\nFAILURE: Some workspace test suites failed.")
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
