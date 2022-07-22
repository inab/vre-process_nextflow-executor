#!/bin/sh

set -e

rm -rf TCGA_benchmarking_workflow TCGA_full_data
git clone --depth 1 --filter=blob:none --sparse https://github.com/inab/TCGA_benchmarking_workflow
cd TCGA_benchmarking_workflow && git sparse-checkout set TCGA_sample_data
mv TCGA_sample_data ../TCGA_full_data
cd .. && rm -rf TCGA_benchmarking_workflow

