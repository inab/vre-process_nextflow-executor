In order to fetch the dataset used for LRGASP challenge 3 test you have to run
`materialize-data.sh` script, like:

```bash
./materialize-data.sh
```

The script will fetch the workflow's repo and generate the reference
dataset expected by the workflow.


In case you want to build a local image of the containers, instead of
using the official ones, you have to run next command in order to
materialize the containers which are needed by the workflow:

```bash
./materialize-containers.sh
```

