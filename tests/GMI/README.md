In order to fetch the dataset used for this test you have to run
`materialize-data.sh` script, like:

```bash
./materialize-data.sh
```

and you have to run next command in order to materialize the
containers which are needed by the workflow:

```bash
./materialize-containers.sh
```

The data will be placed at `datasets`, fetched from
<https://github.com/inab/openebench_gmi/tree/master/datasets>
