# OpenEBench VRE Nextflow Executor

This repository contains the Nextflow executor used inside the OpenEBench
VRE instance. The execution is done following the very secure docker-in-docker
approach.

The executor is a python wrapper which is able to understand the way
inputs and outputs are defined by OpenVRE. It expects to receive from VRE both
`nextflow_repo_uri` and `nextflow_repo_tag` input parameters in order to
learn where the workflow to be run can be fetched. These parameters are
used to issue a `git clone -b nextflow_repo_tag nextflow_repo_uri` command
in order to materialize the workflow in a given directory.

If the executor also receives a `nextflow_repo_reldir`, this relative
directory within the folder containing the materialized workflow will
be used to find the `nextflow.config` file which should be available in
any minimally documented Nextflow workflow.

If the executor also receives a `nextflow_repo_profile`, this profile
should exist in the `nextflow.config` file, and it will be used when
the workflow is executed. By default, `docker` profile is expected.
You can tell no explicit profile to be used just declaring `nextflow_repo_profile`
either empty or null.

Through this configuration file the executor can learn several details:

* The workflow entry point through the `mainScript` directive.
* The minimal required version of Nextflow through `nextflowVersion`.

Right now, only this last one is taken into account.

The `project` input parameter tells the wrapper where the results and
other final files can be stored. If that directory contains an archived
version of the workflow, which usually happens when a workflow is re-run,
then it will be used instead of fetching it either from the workflow
cache or from internet.

As this executor was created for OpenEBench, there are several hardcoded
expected input parameters which should be understood by the workflow to
be run: `challenges_ids`, `participant_id`, `input`, `goldstandard_dir`,
`public_ref_dir`, `assess_dir`.

There are also several hardcoded expected parameters which rule out where
the outputs and metadata are stored: `statsdir`, `outdir`, `otherdir`.

The executor will pass to Nextflow other additional parameters which
OpenVRE has declared in its metadata. When some of this parameters represent
a path, it has to fulfil some restrictions: the path should be a descendant
of any of the other required paths, like for instance `public_ref_dir`;
the path should be managed as such inside the workflow, so docker instance
volume mappings are properly done before each process step is run.

## Requirements
Before the first run of the wrapper, follow the installation instructions
in [INSTALL.md](INSTALL.md).

Once the dependencies are installed, a `VRE_NF_RUNNER_py.ini` deployment
configuration file is needed in order to know the default Nextflow version
to use, the directory where the workflows should be cached, etc...

You can find the template configuration file at [VRE_NF_RUNNER_py.ini.template](VRE_NF_RUNNER_py.ini.template),
with all the understood deployment setup parameters described, and either
declared or commented.

## Test your workflow without OpenVRE

If you want to test your own benchmarking workflow before deploying it
to OpenEBench VRE, you can use the script [test_VRE_NF_RUNNER.sh](test_VRE_NF_RUNNER.sh).

The currently available tests are the different subdirectories at
[tests](tests) directory. Each subdirectory has a `README.md` file
describing how to materialize the needed datasets and containers for that 
specific test. Usually, they are in the form of `materialize-data.sh` and
`materialize-containers.sh` scripts, which should be run from within the
test directory.

Next commands (which should be run once) show how to materialize both the containers and datasets needed by the [TCGA test](tests/TCGA):

```bash
cd tests/TCGA
bash ./materialize-data.sh
bash ./materialize-containers.sh
```

Next command shows how run the tests from TCGA example:

```bash
./test_VRE_NF_RUNNER.sh TCGA
```

which will create a fake project directory at `TCGA-test`, and it will use
the files `config.json` and `in_metadata.json` from the directory
[tests/TCGA] to read the parameters, inputs and expected outputs, and the
relative or absolute path of the input files and directories. Relative paths
are interpreted from the very same directory where the script is run.
Both JSON files follow the very same format OpenVRE uses.

If you want to test your own workflows with your own metadata, you should
to mimic one of the existing templates inside [tests](tests).
