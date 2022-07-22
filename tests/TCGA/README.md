In order to fetch the dataset used for this test you have to run
`.materialize.sh` script, like:

```bash
./materialize-data.sh
```

and you have to run next command in order to materialize the
containers which are needed by the workflow:

```bash
./materialize-containers.sh
```

The data will be placed at `TCGA_full_data`, fetched from
<https://github.com/inab/TCGA_benchmarking_workflow/tree/master/TCGA_sample_data>

The data of that remote resource has been derived from the materials of next manuscript:

[Comprehensive Characterization of Cancer Driver Genes and Mutations](https://www.cell.com/cell/fulltext/S0092-8674%2818%2930237-X?code=cell-site), Bailey et al, 2018, Cell

[![doi:10.1016/j.cell.2018.02.060](https://img.shields.io/badge/doi-10.1016%2Fj.cell.2018.02.060-green.svg)](https://doi.org/10.1016/j.cell.2018.02.060) 

## Contents:
- Folder [data](./data) contains benchmarking metrics results from the 2018 TCGA-PanCancer benchmark for the 34 analyzed
cancer types. Those files follow the structure of the 'aggregation' datasets from the [Elixir
    Benchmarking Data Model](https://github.com/inab/benchmarking-data-model). Json schemas for those datasets can be
    found [here](https://github.com/inab/OpenEBench_scientific_visualizer/blob/master/benchmarking_data_model/inline_data_visualizer.json)
- Folder [metrics_ref_datasets](./metrics_ref_datasets)
contains the gold standards defined by the community for each of the cancer types.
- Folder[public_ref](./public_ref) contains the 
reference data used by the community for validation/predictions.
- [All_Together.txt](./All_Together.txt) is a gene predictions file which can be used as input to test the workflow. 
