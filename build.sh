#!/bin/sh
set -eu
cd "$(dirname "$0")"
test "$(uname -m)" = riscv64 || { echo 'Build on K3 (riscv64), not the Mac.' >&2; exit 1; }
python3 prepare_data.py
mkdir -p bin
g++ -O3 -std=c++17 -ffp-contract=off -fopenmp -Wall -Wextra native/brain.cpp -o bin/siliconfly-brain
echo 'K3 native backend built'
