#!/usr/bin/env bash
set -euo pipefail

pvlib_revision=c78b50f4337ecbe536a961336ca91a1176efc0e8
task_revision=3d07b464b7b311a0cbfb5ed5b2d8a3b96f84a33d
candidate_revision=06b43c9d75c66c7caed22a6be0abc97627887a13
task=tasks/pvlib__pvlib-python-1606
evidence="$(pwd)/.adl/pvlib-evidence"
mkdir -p "$evidence"
scratch=$(mktemp -d)
trap 'rm -r "$scratch"' EXIT

python3 -m venv "$scratch/env"
export PATH="$scratch/env/bin:$PATH"
python -m pip install 'numpy==2.0.2' 'pandas==2.3.3' 'scipy==1.13.1' \
  'pytest==8.4.2' 'setuptools==80.10.2' 'pytz' 'requests' 'h5py' 'matplotlib<3.10'

curl --fail --silent --show-error --location \
  "https://codeload.github.com/pvlib/pvlib-python/tar.gz/$pvlib_revision" \
  --output "$scratch/source.tar.gz"
tar -xf "$scratch/source.tar.gz" -C "$scratch"
cd "$scratch/pvlib-python-$pvlib_revision"
git init -q
for patch in gold.patch test.patch; do
  curl --fail --silent --show-error --location \
    "https://raw.githubusercontent.com/SWE-bench/swe-bench-tasks/$task_revision/$task/$patch" \
    --output "$scratch/$patch"
  git apply "$scratch/$patch"
done

status=0
python -m pytest -rA pvlib/tests/test_tools.py > "$evidence/before.txt" 2>&1 || status=$?
test "$status" -eq 4
grep -F 'removed in the NumPy 2.0 release' "$evidence/before.txt"

curl --fail --silent --show-error --location \
  "https://raw.githubusercontent.com/archit15singh/swe-bench-tasks/$candidate_revision/$task/eval.sh" \
  --output "$scratch/eval.sh"
bash -n "$scratch/eval.sh"
grep -Fx "python -m pip install -q 'numpy<2' || exit \$?" "$scratch/eval.sh" > "$scratch/repair.sh"
bash -e "$scratch/repair.sh"

python -c 'import numpy; print(numpy.__version__); assert numpy.__version__.startswith("1.")'
python -m pytest -rA pvlib/tests/test_tools.py | tee "$evidence/after.txt"
grep -F 'PASSED pvlib/tests/test_tools.py::test__golden_sect_DataFrame_vector' "$evidence/after.txt"
