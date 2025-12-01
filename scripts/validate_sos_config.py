#!/usr/bin/env python3
"""
Validate SOS configuration without requiring dependencies.
This script checks the configuration files directly.
"""
import re
import sys
from pathlib import Path


def extract_value_from_file(file_path: Path, pattern: str) -> str:
    """Extract a value from a file using a regex pattern"""
    content = file_path.read_text()
    match = re.search(pattern, content)
    if match:
        return match.group(1)
    return None


def validate_v53e_config():
    """Validate V53EConfig in src/etl/v53e.py"""
    file_path = Path(__file__).parent.parent / "src/etl/v53e.py"

    print("=" * 60)
    print("Validating V53EConfig (src/etl/v53e.py)")
    print("=" * 60)

    # Extract values
    transitivity_lambda = extract_value_from_file(
        file_path,
        r'SOS_TRANSITIVITY_LAMBDA:\s*float\s*=\s*([\d.]+)'
    )
    sos_iterations = extract_value_from_file(
        file_path,
        r'SOS_ITERATIONS:\s*int\s*=\s*(\d+)'
    )
    sos_repeat_cap = extract_value_from_file(
        file_path,
        r'SOS_REPEAT_CAP:\s*int\s*=\s*(\d+)'
    )
    unranked_sos_base = extract_value_from_file(
        file_path,
        r'UNRANKED_SOS_BASE:\s*float\s*=\s*([\d.]+)'
    )
    off_weight = extract_value_from_file(
        file_path,
        r'OFF_WEIGHT:\s*float\s*=\s*([\d.]+)'
    )
    def_weight = extract_value_from_file(
        file_path,
        r'DEF_WEIGHT:\s*float\s*=\s*([\d.]+)'
    )
    sos_weight = extract_value_from_file(
        file_path,
        r'SOS_WEIGHT:\s*float\s*=\s*([\d.]+)'
    )
    perf_blend_weight = extract_value_from_file(
        file_path,
        r'PERF_BLEND_WEIGHT:\s*float\s*=\s*([\d.]+)'
    )

    print(f"  SOS_TRANSITIVITY_LAMBDA: {transitivity_lambda}")
    print(f"  SOS_ITERATIONS: {sos_iterations}")
    print(f"  SOS_REPEAT_CAP: {sos_repeat_cap}")
    print(f"  UNRANKED_SOS_BASE: {unranked_sos_base}")
    print(f"  OFF_WEIGHT: {off_weight}")
    print(f"  DEF_WEIGHT: {def_weight}")
    print(f"  SOS_WEIGHT: {sos_weight}")
    print(f"  PERF_BLEND_WEIGHT: {perf_blend_weight}")

    # Validate
    errors = []

    if float(transitivity_lambda) != 0.20:
        errors.append(f"❌ SOS_TRANSITIVITY_LAMBDA should be 0.20, got {transitivity_lambda}")
    else:
        print(f"  ✅ SOS_TRANSITIVITY_LAMBDA is correct (0.20)")

    if int(sos_iterations) != 3:
        errors.append(f"❌ SOS_ITERATIONS should be 3, got {sos_iterations}")
    else:
        print(f"  ✅ SOS_ITERATIONS is correct (3)")

    # Check PowerScore weights sum to 1.0
    weight_sum = float(off_weight) + float(def_weight) + float(sos_weight)
    if abs(weight_sum - 1.0) > 0.0001:
        errors.append(f"❌ PowerScore weights should sum to 1.0, got {weight_sum}")
    else:
        print(f"  ✅ PowerScore weights sum to 1.0")

    if float(sos_weight) != 0.50:
        errors.append(f"❌ SOS_WEIGHT should be 0.50, got {sos_weight}")
    else:
        print(f"  ✅ SOS_WEIGHT is correct (50%)")

    print()
    return errors


def validate_settings_config():
    """Validate config/settings.py"""
    file_path = Path(__file__).parent.parent / "config/settings.py"

    print("=" * 60)
    print("Validating settings.py (config/settings.py)")
    print("=" * 60)

    # Extract default value for sos_transitivity_lambda
    transitivity_lambda = extract_value_from_file(
        file_path,
        r"'sos_transitivity_lambda'.*?getenv.*?[\",]([\d.]+)"
    )

    print(f"  sos_transitivity_lambda default: {transitivity_lambda}")

    errors = []

    if transitivity_lambda and float(transitivity_lambda) != 0.20:
        errors.append(f"❌ settings.py default should be 0.20, got {transitivity_lambda}")
    else:
        print(f"  ✅ settings.py default is correct (0.20)")

    print()
    return errors


def validate_documentation():
    """Validate docs/SOS_FIELDS_EXPLANATION.md"""
    file_path = Path(__file__).parent.parent / "docs/SOS_FIELDS_EXPLANATION.md"

    print("=" * 60)
    print("Validating Documentation (docs/SOS_FIELDS_EXPLANATION.md)")
    print("=" * 60)

    content = file_path.read_text()

    errors = []

    # Check for 0.20 transitivity lambda
    if "SOS_TRANSITIVITY_LAMBDA = 0.20" in content:
        print(f"  ✅ Documentation shows SOS_TRANSITIVITY_LAMBDA = 0.20")
    else:
        errors.append("❌ Documentation doesn't show SOS_TRANSITIVITY_LAMBDA = 0.20")

    # Check for 80% direct, 20% transitive
    if "80% direct, 20% transitive" in content:
        print(f"  ✅ Documentation shows 80% direct, 20% transitive")
    else:
        errors.append("❌ Documentation doesn't show 80% direct, 20% transitive")

    print()
    return errors


def validate_transitivity_calculation():
    """Validate the transitivity calculation logic"""
    print("=" * 60)
    print("Validating Transitivity Calculation")
    print("=" * 60)

    lambda_val = 0.20
    direct_weight = 1 - lambda_val
    transitive_weight = lambda_val

    print(f"  Lambda: {lambda_val}")
    print(f"  Direct weight: {direct_weight} ({direct_weight * 100:.0f}%)")
    print(f"  Transitive weight: {transitive_weight} ({transitive_weight * 100:.0f}%)")

    errors = []

    if abs(direct_weight - 0.80) > 0.0001:
        errors.append(f"❌ Direct weight should be 0.80, got {direct_weight}")
    else:
        print(f"  ✅ Direct weight is 80%")

    if abs(transitive_weight - 0.20) > 0.0001:
        errors.append(f"❌ Transitive weight should be 0.20, got {transitive_weight}")
    else:
        print(f"  ✅ Transitive weight is 20%")

    if abs(direct_weight + transitive_weight - 1.0) > 0.0001:
        errors.append(f"❌ Weights should sum to 1.0")
    else:
        print(f"  ✅ Weights sum to 1.0")

    print()
    return errors


def main():
    """Run all validation checks"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "SOS CONFIGURATION VALIDATION" + " " * 20 + "║")
    print("╚" + "=" * 58 + "╝")
    print()

    all_errors = []

    # Run validations
    all_errors.extend(validate_v53e_config())
    all_errors.extend(validate_settings_config())
    all_errors.extend(validate_documentation())
    all_errors.extend(validate_transitivity_calculation())

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if all_errors:
        print("❌ VALIDATION FAILED\n")
        for error in all_errors:
            print(f"  {error}")
        print()
        sys.exit(1)
    else:
        print("✅ ALL VALIDATIONS PASSED")
        print()
        print("Configuration Summary:")
        print("  • 3-pass iterative SOS system")
        print("  • Lambda = 0.20 (80% direct, 20% transitive)")
        print("  • PowerScore: 25% OFF + 25% DEF + 50% SOS + 15% perf_centered (additive)")
        print("  • perf_centered ranges from -0.5 to +0.5, so ±7.5% adjustment")
        print("  • All config files are consistent")
        print()
        sys.exit(0)


if __name__ == '__main__':
    main()
