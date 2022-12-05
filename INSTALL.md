# OpenEBench VRE Nextflow Executor install instructions

## Install the system dependencies needed to install and run the wrapper (and materializing its tests' datasets):

1. The latest version of the VRE Nextflow wrapper should be fetched through git. Also, the wrapper itself uses `git` command line to materialize workflows, so `git` command must be reachable through PATH environment variable:

  ```bash
  sudo apt-get -y install git
  ```

2. Install Python's' `venv` module, which also fetches `pip`:

  ```bash
  # This first one is needed to have venv module
  sudo apt-get -y install python3-venv
  ```

3. Docker must be installed and running in the machine, as it is expected that Nextflow workflows use docker containers. Next docker installation instructions are valid for Ubuntu / Debian:

  ```bash
  # These are pre-requisites for docker, described at
  # https://docs.docker.com/install/linux/docker-ce/ubuntu/#install-using-the-repository
  sudo apt update
  sudo apt install apt-transport-https ca-certificates curl software-properties-common
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
  sudo add-apt-repository \
     "deb [arch=amd64] https://download.docker.com/linux/ubuntu \
     $(lsb_release -cs) \
     stable"
  
  # This is the installation of the docker package as such
  sudo apt update
  sudo apt install docker-ce
  ```

 Remember to add the username to the `docker` group, using for instance next recipe.

 ```bash
 sudo usermod -a -G docker $USER
 ```
 
 Once this last step is done, it is recommended to restart the Linux graphical session, so the belonging to the docker group is visible to all the processes of the user.
 
4. [jq](https://stedolan.github.io/jq/) command line is used to ensure reproducible tests, as it helps peeking the JSON config files from the tests:

  ```bash
  sudo apt install jq
  ```

## Fetch the VRE Nextflow repo and install the dependencies used by the wrapper

1. The repo latest version can be materialized through next command:

  ```bash
  git clone https://github.com/inab/vre-process_nextflow-executor.git
  ```

2. Install the wrapper dependencies

  ```bash
  cd vre-process_nextflow-executor
  python3 -m venv .py3Env
  source .py3Env/bin/activate
  pip install --upgrade pip wheel
  pip install -r requirements.txt
  ```
  
3. Create a `VRE_NF_RUNNER.py.ini` file, and customize it accordingly to your machine. You can use [VRE_NF_RUNNER.py.ini.template](VRE_NF_RUNNER.py.ini.template) as an starting point:

    ```bash
    cp VRE_NF_RUNNER.py.ini.template VRE_NF_RUNNER.py.ini
    ```

4. Docker image with [Nextflow](https://www.nextflow.io/) is fetched on first wrapper invocation. The specific version is determined both by the constraints within the workflow being run and the content of `VRE_NF_RUNNER.py.ini`.
