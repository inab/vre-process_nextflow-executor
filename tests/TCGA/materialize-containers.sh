#!/bin/sh

set -e

rm -rf TCGA_benchmarking_dockers
git clone --depth 1 https://github.com/inab/TCGA_benchmarking_dockers
cd TCGA_benchmarking_dockers && ./build.sh 1.0
cd .. && rm -rf TCGA_benchmarking_dockers

