"""
.. See the NOTICE file distributed with this work for additional information
   regarding copyright ownership.

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
"""
from __future__ import print_function

import atexit
import sys
import os
import re
import configparser
import subprocess
import tempfile
import json
import fnmatch
import tarfile
import shutil
import io
import datetime

import hashlib

import uuid

from utils import logger

try:
    if hasattr(sys, '_run_from_cmdl') is True:
        raise ImportError
    from pycompss.api.parameter import FILE_IN, FILE_OUT
    from pycompss.api.task import task
    from pycompss.api.api import compss_wait_on
except ImportError:
#    logger.warn("[Warning] Cannot import \"pycompss\" API packages.")
#    logger.warn("          Using mock decorators.")

    from utils.dummy_pycompss import FILE_IN, FILE_OUT # pylint: disable=ungrouped-imports
    from utils.dummy_pycompss import task # pylint: disable=ungrouped-imports
    from utils.dummy_pycompss import compss_wait_on # pylint: disable=ungrouped-imports

from basic_modules.tool import Tool
from basic_modules.metadata import Metadata

import tempfile

# ------------------------------------------------------------------------------

def copy2_nofollow(src, dest):
    shutil.copy2(src, dest, follow_symlinks=False)

class WF_RUNNER(Tool):
    CONFIG_DIR_KEY = "__config_dir__"

    """
    Tool for writing to a file
    """
    DEFAULT_NXF_IMAGE='nextflow/nextflow'
    DEFAULT_NXF_VERSION='19.04.1'
    DEFAULT_WF_BASEDIR='WF-checkouts'
    DEFAULT_MAX_RETRIES=5
    DEFAULT_MAX_CPUS=4
    DEFAULT_WORKFLOW_PROFILE = 'docker'
    
    DEFAULT_DOCKER_CMD='docker'
    DEFAULT_GIT_CMD='git'
    
    MASKED_KEYS = {
        'execution',
        'project',
        'description',
        'nextflow_repo_uri',
        'nextflow_repo_tag',
        'nextflow_repo_reldir',
        'nextflow_repo_profile',
        CONFIG_DIR_KEY,
    }
    
    MASKED_OUT_KEYS = { 'metrics', 'tar_view', 'tar_nf_stats', 'tar_other', 'workflow_archive' }
    
    IMG_FILE_TYPES = {
        'png',
        'svg',
        'pdf',
        'jpg',
        'tif'
    }
    
    def __init__(self, configuration=None):
        """
        Init function
        """
        logger.info("OpenEBench VRE Nexflow pipeline runner")
        super().__init__()

        self.timestamp_str = datetime.datetime.now().replace(microsecond=0).strftime("%Y%m%dT%H%M%S")
        
        local_config = configparser.ConfigParser()
        local_config_filename = sys.argv[0] + '.ini'
        if not os.path.exists(local_config_filename):
            local_config_filename_template = local_config_filename + '.template'
            try:
                shutil.copy2(local_config_filename_template, local_config_filename)
                logger.debug("Configuration file {} initialized with the default template {}".format(local_config_filename, local_config_filename_template))
            except:
                logger.exception("Unable to copy configuration file template {} to ´{}".format(local_config_filename_template, local_config_filename))
                # This could happen if the installation dir belongs to
                # a different user, so let's go through the default path
                local_config_filename = local_config_filename_template
        
        # In any case ... let's try reading
        local_config.read(local_config_filename)
        
        # Setup parameters
        self.nxf_image = local_config.get('nextflow','docker_image')  if local_config.has_option('nextflow','docker_image') else self.DEFAULT_NXF_IMAGE
        self.nxf_version = local_config.get('nextflow','version')  if local_config.has_option('nextflow','version') else self.DEFAULT_NXF_VERSION
        self.max_retries = int(local_config.get('nextflow','max-retries'))  if local_config.has_option('nextflow','max-retries') else self.DEFAULT_MAX_RETRIES
        self.max_cpus = int(local_config.get('nextflow','max-cpus'))  if local_config.has_option('nextflow','max-cpus') else self.DEFAULT_MAX_CPUS
        
        self.wf_basedir = os.path.abspath(os.path.expanduser(local_config.get('workflows','basedir')  if local_config.has_option('workflows','basedir') else self.DEFAULT_WF_BASEDIR))

        # Where the external commands should be located
        self.docker_cmd = local_config.get('defaults','docker_cmd')  if local_config.has_option('defaults','docker_cmd') else self.DEFAULT_DOCKER_CMD
        self.git_cmd = local_config.get('defaults','git_cmd')  if local_config.has_option('defaults','git_cmd') else self.DEFAULT_GIT_CMD
        
        if configuration is None:
            configuration = {}

        self.configuration.update(configuration)

        # This is needed to resolve relative input paths
        self.config_dir = self.configuration.get(self.CONFIG_DIR_KEY, os.getcwd())
        # Arrays are serialized
        for k,v in self.configuration.items():
            if isinstance(v,list):
                self.configuration[k] = ' '.join(v)
        
        self.populable_outputs = {}

    def fetchNextflow(self,nextflow_version):
        # Now, we have to assure the nextflow image is already here
        docker_tag = self.nxf_image+':'+nextflow_version
        checkimage_params = [
            self.docker_cmd,"images","--format","{{.ID}}\t{{.Tag}}",docker_tag
        ]
        
        with tempfile.NamedTemporaryFile() as checkimage_stdout:
            with tempfile.NamedTemporaryFile() as checkimage_stderr:
                retval = subprocess.call(checkimage_params,stdout=checkimage_stdout,stderr=checkimage_stderr)

                if retval != 0:
                    # Reading the output and error for the report
                    with open(checkimage_stdout.name,"r") as c_stF:
                        checkimage_stdout_v = c_stF.read()
                    with open(checkimage_stderr.name,"r") as c_stF:
                        checkimage_stderr_v = c_stF.read()
                    
                    errstr = "ERROR: VRE Nextflow Runner failed while checking Nextflow image (retval {}). Tag: {}\n======\nSTDOUT\n======\n{}\n======\nSTDERR\n======\n{}".format(retval,docker_tag,checkimage_stdout_v,checkimage_stderr_v)
                    logger.fatal(errstr)
                    raise Exception(errstr)
            
            do_pull_image = os.path.getsize(checkimage_stdout.name) == 0
                    
        
        if do_pull_image:
            # The image is not here yet
            pullimage_params = [
                self.docker_cmd,"pull",docker_tag
            ]
            with tempfile.NamedTemporaryFile() as pullimage_stdout:
                with tempfile.NamedTemporaryFile() as pullimage_stderr:
                    retval = subprocess.call(pullimage_params,stdout=pullimage_stdout,stderr=pullimage_stderr)
                    if retval != 0:
                        # Reading the output and error for the report
                        with open(pullimage_stdout.name,"r") as c_stF:
                            pullimage_stdout_v = c_stF.read()
                        with open(pullimage_stderr.name,"r") as c_stF:
                            pullimage_stderr_v = c_stF.read()
                        
                        # It failed!
                        errstr = "ERROR: VRE Nextflow Runner failed while pulling Nextflow image (retval {}). Tag: {}\n======\nSTDOUT\n======\n{}\n======\nSTDERR\n======\n{}".format(retval,docker_tag,pullimage_stdout_v,pullimage_stderr_v)
                        logger.fatal(errstr)
                        raise Exception(errstr)

        return docker_tag

    def doMaterializeRepo(self, git_uri, git_tag):
        repo_hashed_id = hashlib.sha1(git_uri.encode('utf-8')).hexdigest()
        repo_hashed_tag_id = hashlib.sha1(git_tag.encode('utf-8')).hexdigest()
        
        # Assure directory exists before next step
        repo_destdir = os.path.join(self.wf_basedir,repo_hashed_id)
        if not os.path.exists(repo_destdir):
            try:
                os.makedirs(repo_destdir)
            except IOError as error:
                errstr = "ERROR: Unable to create intermediate directories for repo {}. ".format(git_uri,);
                raise Exception(errstr)
        
        repo_tag_destdir = os.path.join(repo_destdir,repo_hashed_tag_id)
        # We are assuming that, if the directory does exist, it contains the repo
        if not os.path.exists(repo_tag_destdir):
            # Try cloing the repository without initial checkout
            gitclone_params = [
                self.git_cmd,'clone','-n','--recurse-submodules',git_uri,repo_tag_destdir
            ]
            
            # Now, checkout the specific commit
            gitcheckout_params = [
                self.git_cmd,'checkout',git_tag
            ]
            
            # Last, initialize submodules
            gitsubmodule_params = [
                self.git_cmd,'submodule','update','--init'
            ]
            
            with tempfile.NamedTemporaryFile() as git_stdout:
                with tempfile.NamedTemporaryFile() as git_stderr:
                    # First, bare clone
                    retval = subprocess.call(gitclone_params,stdout=git_stdout,stderr=git_stderr)
                    # Then, checkout
                    if retval == 0:
                        retval = subprocess.Popen(gitcheckout_params,stdout=git_stdout,stderr=git_stderr,cwd=repo_tag_destdir).wait()
                    # Last, submodule preparation
                    if retval == 0:
                        retval = subprocess.Popen(gitsubmodule_params,stdout=git_stdout,stderr=git_stderr,cwd=repo_tag_destdir).wait()
                    
                    # Proper error handling
                    if retval != 0:
                        # Reading the output and error for the report
                        with open(git_stdout.name,"r") as c_stF:
                            git_stdout_v = c_stF.read()
                        with open(git_stderr.name,"r") as c_stF:
                            git_stderr_v = c_stF.read()
                        
                        errstr = "ERROR: VRE Nextflow Runner could not pull '{}' (tag '{}'). Retval {}\n======\nSTDOUT\n======\n{}\n======\nSTDERR\n======\n{}".format(git_uri,git_tag,retval,git_stdout_v,git_stderr_v)
                        raise Exception(errstr)
	 
        return repo_tag_destdir

    def guessNextflowVersion(self,repo_tag_destdir):
        # Now, let's guess the repo and nextflow version
        nextflow_version = self.nxf_version
        try:
            with open(os.path.join(repo_tag_destdir,'nextflow.config'),"r") as nc_config:
                pat = re.compile(r"nextflowVersion *= *['\"](!?[>=]*)([^ ]+)['\"]")
                for line in nc_config:
                    matched = pat.search(line)
                    if matched:
                        new_nextflow_version = matched.group(2)
                        modifier = matched.group(1)
                        if len(modifier) > 0 and modifier[0] == '!':
                            nextflow_version = new_nextflow_version
                        elif new_nextflow_version >= nextflow_version:
                            nextflow_version = new_nextflow_version
                        break
        except:
            pass
 
        return nextflow_version
    
    def identifyRepo(self,repo_dir):
        remote_url = None
        remote_sha = None
        is_tainted = None

        # These commands must be run using repo_dir as working directory
        gitremote_params = [
            self.git_cmd, "remote", "get-url", "origin"
        ]

        with tempfile.SpooledTemporaryFile(mode='w+t') as git_stdout, tempfile.SpooledTemporaryFile(mode='w+t') as git_stderr:
            # First, call git
            retval = subprocess.call(gitremote_params,stdout=git_stdout,stderr=git_stderr,cwd=repo_dir)
            # Then, get the value
            git_stdout.seek(0)
            if retval == 0:
                remote_url = git_stdout.readline().strip()
            else:
                # Reading the output and error for the report
                gitremote_stdout_v = git_stdout.read()
                git_stderr.seek(0)
                gitremote_stderr_v = git_stderr.read()
                
                errstr = "VRE Nextflow Runner failed while checking workflow remote (retval {})\n======\nSTDOUT\n======\n{}\n======\nSTDERR\n======\n{}".format(retval,gitremote_stdout_v,gitremote_stderr_v)
                logger.warning(errstr)
        

        gitrevparse_params = [
            self.git_cmd, "rev-parse","HEAD"
        ]

        with tempfile.SpooledTemporaryFile(mode='w+t') as git_stdout, tempfile.SpooledTemporaryFile(mode='w+t') as git_stderr:
            # First, call git
            retval = subprocess.call(gitrevparse_params,stdout=git_stdout,stderr=git_stderr,cwd=repo_dir)
            # Then, get the value
            git_stdout.seek(0)
            if retval == 0:
                remote_sha = git_stdout.readline().strip()
            else:
                # Reading the output and error for the report
                gitrevparse_stdout_v = git_stdout.read()
                git_stderr.seek(0)
                gitrevparse_stderr_v = git_stderr.read()
                
                errstr = "VRE Nextflow Runner failed while checking workflow HEAD (retval {})\n======\nSTDOUT\n======\n{}\n======\nSTDERR\n======\n{}".format(retval,gitrevparse_stdout_v,gitrevparse_stderr_v)
                logger.warning(errstr)

        
        gitstatus_params = [
            self.git_cmd, "status","--porcelain"
        ]

        with tempfile.SpooledTemporaryFile(mode='w+t') as git_stdout, tempfile.SpooledTemporaryFile(mode='w+t') as git_stderr:
            # First, call git
            retval = subprocess.call(gitstatus_params,stdout=git_stdout,stderr=git_stderr,cwd=repo_dir)
            # Then, get the value
            git_stdout.seek(0)
            if retval == 0:
                statusmsg = git_stdout.read()
                if len(statusmsg) > 0:
                    is_tainted = statusmsg
            else:
                # Reading the output and error for the report
                gitstatus_stdout_v = git_stdout.read()
                git_stderr.seek(0)
                gitstatus_stderr_v = git_stderr.read()
                
                errstr = "VRE Nextflow Runner failed while checking workflow taint state (retval {})\n======\nSTDOUT\n======\n{}\n======\nSTDERR\n======\n{}".format(retval,gitstatus_stdout_v,gitstatus_stderr_v)
                logger.warning(errstr)

        return remote_url, remote_sha , is_tainted
    
    def packDir(self, resultsDir, destTarFile, basePackdir='data'):
        # This is only needed when a manifest must be generated
        
        #for metrics_file in os.listdir(resultsDir):
        #        abs_metrics_file = os.path.join(resultsDir, metrics_file)
        #        if fnmatch.fnmatch(metrics_file,"*.json") and os.path.isfile(abs_metrics_file):
        #                with io.open(abs_metrics_file,mode='r',encoding="utf-8") as f:
        #                        metrics = json.load(f)
        #                        metricsArray.append(metrics)
        #
        #with io.open(metrics_loc, mode='w', encoding="utf-8") as f:
        #        jdata = json.dumps(metricsArray, sort_keys=True, indent=4, separators=(',', ': '))
        #        f.write(unicode(jdata,"utf-8"))
        
        # And create the MuG/VRE tar file
        #with tarfile.open(destTarFile,mode='w:gz',bufsize=25*1024*1024) as tar:
        #    tar.add(resultsDir,arcname=basePackdir,recursive=True)

        subprocess.run(["tar", "--transform", "s#{0}#{1}#".format(resultsDir.lstrip('/'), basePackdir), "-c","-z","-f", destTarFile,resultsDir], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Unpacks an archive to a given directory, and it returns the
    # composed path of the first entry, if it is a directory, or
    # the destination directory otherwise
    def unpackDir(self,originTarFile,destdir):
        retval = None

        with tarfile.open(originTarFile,mode='r:*',bufsize=1024*1024) as tar:
            first_member = tar.next()
            if first_member is not None:
                retval = os.path.join(destdir,first_member.name)  if first_member.isdir()  else destdir
                tar.extractall(path=destdir)

        return retval
        
    INPUT_KEY = 'input'
    
    # TODO: fix or remove annotation below
    @task(returns=bool, inputs_locs=FILE_IN, goldstandard_dir_loc=FILE_IN, assess_dir_loc=FILE_IN, public_ref_dir_loc=FILE_IN, results_loc=FILE_OUT, stats_loc=FILE_OUT, other_loc=FILE_OUT, dest_workflow_archive=FILE_OUT, isModifier=False)
    def validate_and_assess(self, inputs_locs, results_loc, stats_loc, other_loc, dest_workflow_archive):  # pylint: disable=no-self-use
        # Temporary directory is removed at the end
        # being compressed to an archive
        try:
            workdir = tempfile.mkdtemp(prefix="vre-",suffix="-job")
        except Exception as error:
            logger.fatal("ERROR: Unable to create instantiation working directory. Error: "+str(error))
            return False
        
        # These paths are badly needed
        # This one should be used to resolve relative inputs
        # (a relative project path is resolved against config dirname)
        do_docker_unconfined = self.configuration.get("docker_unconfined", False)
        project_path = self.configuration.get('project','.')
        if not os.path.isabs(project_path):
            project_path = os.path.normpath(os.path.join(self.config_dir, project_path))
        # This one should be used to resolve relative outputs
        # (a relative execution path is resolved against working directory)
        execution_path = os.path.abspath(self.configuration.get('execution', '.'))

        nextflow_repo_uri = self.configuration.get('nextflow_repo_uri')
        nextflow_repo_tag = self.configuration.get('nextflow_repo_tag')
        nextflow_repo_reldir = self.configuration.get('nextflow_repo_reldir')
        nextflow_repo_profile = self.configuration.get('nextflow_repo_profile', self.DEFAULT_WORKFLOW_PROFILE)
        if (nextflow_repo_uri is None) or (nextflow_repo_tag is None):
            logger.fatal("FATAL ERROR: both 'nextflow_repo_uri' and 'nextflow_repo_tag' parameters must be defined")
            return False
        
        replay_workflow = os.path.exists(dest_workflow_archive)
        if not replay_workflow:
            # First, we need to materialize the workflow
            # checking out the repo to be used
            try:
                repo_dir = self.doMaterializeRepo(nextflow_repo_uri,nextflow_repo_tag)
                logger.info("Fetched workflow: "+nextflow_repo_uri+" ("+nextflow_repo_tag+")")
                self.packDir(repo_dir, dest_workflow_archive, basePackdir='workflow-'+nextflow_repo_tag)
            except Exception as error:
                logger.fatal("While materializing repo: "+type(error).__name__ + ': '+str(error))
                return False

        # If the workflow archive already exists, override all the
        # logic, as we are re-running a previous instance
        if os.path.isfile(dest_workflow_archive):
            repo_dir = self.unpackDir(dest_workflow_archive, workdir)
            workflow_dir = repo_dir
        elif os.path.isdir(dest_workflow_archive):
            repo_dir = os.path.join(workdir, ".tmp-wf-{0}_{1}".format(datetime.datetime.now().timestamp(), os.path.basename(dest_workflow_archive)))
            atexit.register(shutil.rmtree, repo_dir)
            shutil.copytree(dest_workflow_archive, repo_dir, copy_function=copy2_nofollow)
            workflow_dir = repo_dir
        else:
            logger.fatal("FATAL ERROR: {0} workflow path is of an unexpected kind".format(dest_workflow_archive))
            return False
        
        if (nextflow_repo_reldir is not None) and len(nextflow_repo_reldir) > 0:
            workflow_dir = os.path.join(workflow_dir, nextflow_repo_reldir)

        # These two values are populated from the workflow checkout info
        new_nextflow_repo_uri , new_nextflow_repo_tag , is_tainted = self.identifyRepo(workflow_dir)
        logger.info("Cached workflow: "+new_nextflow_repo_uri+" ("+new_nextflow_repo_tag+")")

        if new_nextflow_repo_uri!=nextflow_repo_uri or new_nextflow_repo_tag!=nextflow_repo_tag:
            logger.warning("Cached workflow differs from requested one. \n\tExpected: "+nextflow_repo_uri+" ("+nextflow_repo_tag+")\n\tFound: "+new_nextflow_repo_uri+" ("+new_nextflow_repo_tag+")")
            # As we are using this copy, rewrite these variables
            nextflow_repo_uri = new_nextflow_repo_uri
            nextflow_repo_tag = new_nextflow_repo_tag

        logger.debug("\tLocal dir: "+workflow_dir)
        if is_tainted:
            logger.warning("Local copy of the repo is tainted. Report:\n"+is_tainted)
        
        # Guess workflow engine to use
        nextflow_version = self.guessNextflowVersion(workflow_dir)
        logger.info("Nextflow engine to be used: "+nextflow_version)
        
        nextflow_version_tuple = tuple(nextflow_version.split("."))
        
        # It is needed at least with version 20.07.1
        do_workdir_include_vol = nextflow_version_tuple < ("20", "07","1")
        
        # With the version, fetch the engine
        try:
            nxf_image_tag = self.fetchNextflow(nextflow_version)
        except Exception as error:
            logger.fatal("While materializing Nextflow engine "+nextflow_version+": "+type(error).__name__ + ': '+str(error))
            return False
        
        # The directories are being created for the workflow manager, so they have the right owner
        os.makedirs(results_loc)
        os.makedirs(stats_loc)
        os.makedirs(other_loc)
        
        challenges_ids = self.configuration['challenges_ids']
        participant_id = self.configuration['participant_id']
        
        # inputDir = os.path.dirname(input_loc)
        # inputBasename = os.path.basename(input_loc)
        
        # Value needed to compose the Nextflow docker call
        uid = str(os.getuid())
        gid = str(os.getgid())

        # Timezone is needed to get logs properly timed
        try:
            with open("/etc/timezone","r") as tzreader:
                tzstring = tzreader.readline().rstrip()
        except:
            # The default for the worst case
            tzstring = 'Europe/Madrid'
        
        # Temporary directory is removed at the end
        # being compressed to an archive
        try:
            workdir = tempfile.mkdtemp(prefix="vre-",suffix="-job")
        except Exception as error:
            logger.fatal("ERROR: Unable to create nextflow working directory. Error: "+str(error))
            return False
        
        dest_workdir_archive = os.path.join(execution_path, 'nf-workdir.tar.gz')
        
        # Directories required by Nextflow in a Docker
        homedir = os.path.expanduser("~")
        nxf_home_dir = os.path.join(homedir, "NXF_HOMES", nextflow_version, ".nextflow")
        if not os.path.exists(nxf_home_dir):
            try:
                os.makedirs(nxf_home_dir, exist_ok=True)
            except Exception as error:
                logger.fatal("ERROR: Unable to create nextflow assets directory. Error: "+str(error))
                return False
        
        retval_stage = 'validation'
        
        # The fixed parameters
        validation_cmd_pre_vol = [
            self.docker_cmd, "run", "--rm",# "--net", "host",
            "-e", "USER",
            "-e", "NXF_DEBUG",
            "-e", "TZ="+tzstring,
            "-e", "HOME="+homedir,
            "-e", "NXF_HOME=" + nxf_home_dir,
            "-e", "NXF_USRMAP="+uid,
            #"-e", "NXF_DOCKER_OPTS=-u "+uid+":"+gid+" -e HOME="+homedir+" -e TZ="+tzstring+" -v "+workdir+":"+workdir+":rw,rprivate,z -v "+execution_path+":"+execution_path+":rw,rprivate,z",
            #"-e", "NXF_DOCKER_OPTS=-u "+uid+":"+gid+" -e HOME="+homedir+" -e TZ="+tzstring+" -v "+workdir+":"+workdir+":rw,rprivate,z",
            "-v", "/var/run/docker.sock:/var/run/docker.sock:rw,rprivate,z"
        ]
        
        vre_wf_setup_file = os.path.join(workdir, 'vre-wf-setup.config')
        validation_cmd_post_vol = [
            "-w", workdir,
            "--",
            nxf_image_tag,
            "nextflow",
            "run", workflow_dir,
        ]
        
        setup_options: "MutableMapping[str, str]" = {
            "docker.enabled": "true",
            "executor.$local.cpus": str(self.max_cpus),
        }
        with open(vre_wf_setup_file, mode="w", encoding="utf-8") as vF:
            if do_workdir_include_vol:
                workdir_vol = "-v {0}:{0}:rw,rprivate,z ".format(workdir)
            else:
                workdir_vol = ""
            if do_docker_unconfined:
                unconfined_docker = "--security-opt seccomp=unconfined"
            else:
                unconfined_docker = ""
            
            runOptions = " -u {0}:{1} -e HOME={2} -e TZ={3} {4} {5}".format(uid, gid, homedir, tzstring, workdir_vol, unconfined_docker)
            setup_options["docker.runOptions"] = runOptions
            for key, val in setup_options.items():
                pval = '"' + val + '"' if " " in val else val
                print(key + " = " + pval, file=vF)

            if False:
                # Trying to avoid Nextflow DSL2 issues when -c is used
                validation_cmd_post_vol.extend([
                    "-" + key + "=" + val
                    for key, val in setup_options.items()
                ])
            elif True:
                with open(os.path.join(workflow_dir, "nextflow.config"), mode="a", encoding="utf-8") as aH:
                    print('\nincludeConfig "{0}"'.format(vre_wf_setup_file), file=aH)
            else:
                # This one will be enabled in the future in Nextflow versions
                # having bugs https://github.com/nextflow-io/nextflow/issues/4626
                # and https://github.com/nextflow-io/nextflow/issues/2662 fixed
                validation_cmd_post_vol.extend([
                    "-c", vre_wf_setup_file,
                ])
        
        # Use profiles only when they are set up
        if nextflow_repo_profile:
            validation_cmd_post_vol.extend(["-profile", nextflow_repo_profile])
        
        validation_cmd_post_vol_resume = [ *validation_cmd_post_vol , '-resume' ]
        
        # This one will be filled in by the volume parameters passed to docker
        #docker_vol_params = []
        
        # This one will be filled in by the volume meta declarations, used
        # to generate the volume parameters
        volumes = [
            (homedir+'/',"ro,rprivate,z"),
            (nxf_home_dir + "/","rw,rprivate,z"),
            (workdir+'/',"rw,rprivate,z"),
            (execution_path+'/',"rw,rprivate,z"),
            (workflow_dir+'/',"ro,rprivate,z")
        ]
        if not os.path.samefile(project_path, execution_path):
            volumes.insert(0, (project_path+'/',"ro,rprivate,z"))
        
        # These are the parameters, including input and output files and directories
        
        # Parameters which are not input or output files are in the configuration
        variable_params = [
        #    ('challenges_ids',challenges_ids),
        #    ('participant_id',participant_id)
        ]
        for conf_key in self.configuration.keys():
            if conf_key not in self.MASKED_KEYS:
                variable_params.append((conf_key,self.configuration[conf_key]))
        
        
        variable_infile_params = []
        
        failed_parameters = []
        for key_name, val_path in inputs_locs.items():
            if os.path.isabs(val_path):
                abs_val_path = val_path
            else:
                abs_val_path = os.path.normpath(os.path.join(project_path, val_path))
            if not os.path.exists(abs_val_path):
                    logger.fatal("Parameter {0} uses file {1} (resolved as {2}), but it is not available".format(key_name, val_path, abs_val_path))
                    failed_parameters.append(key_name)
            variable_infile_params.append((key_name, abs_val_path))

        if len(failed_parameters) > 0:
            errmsg = "Files for parameters " + " ".join(failed_parameters) + " were not found"
            logger.fatal(errmsg)
            raise Exception(errmsg)
        
        variable_outfile_params = [
            ('statsdir',stats_loc+'/'),
            ('results_dir',results_loc+'/'),
            ('outdir',results_loc + '/'),
            ('otherdir',other_loc+'/')
        ]
        
        # The list of populable outputs
        variable_outfile_params.extend(self.populable_outputs.items())
        logger.warning(json.dumps(variable_outfile_params, indent=4))
        
        # Preparing the RO volumes
        for ro_loc_id,ro_loc_val in variable_infile_params:
            if os.path.exists(ro_loc_val):
                if ro_loc_val.endswith('/') and os.path.isfile(ro_loc_val):
                    ro_loc_val = ro_loc_val[:-1]
                elif not ro_loc_val.endswith('/') and os.path.isdir(ro_loc_val):
                    ro_loc_val += '/'
            volumes.append((ro_loc_val,"ro,rprivate,z"))
            variable_params.append((ro_loc_id,ro_loc_val))
        
        # Preparing the RW volumes
        for rw_loc_id,rw_loc_val in variable_outfile_params:
            # We can skip integrating subpaths of execution_path
            if os.path.commonprefix([os.path.normpath(rw_loc_val), execution_path]) != execution_path:
                if os.path.exists(rw_loc_val):
                    if rw_loc_val.endswith('/') and os.path.isfile(rw_loc_val):
                        rw_loc_val = rw_loc_val[:-1]
                    elif not rw_loc_val.endswith('/') and os.path.isdir(rw_loc_val):
                        rw_loc_val += '/'
                elif rw_loc_val.endswith('/'):
                    # Forcing the creation of the directory
                    try:
                        os.makedirs(rw_loc_val)
                    except:
                        pass
                else:
                    # Forcing the creation of the file
                    # so docker does not create it as a directory
                    with open(rw_loc_val,mode="a") as pop_output_h:
                        logger.debug("Pre-created empty output file (ownership purposes) "+rw_loc_val)
                        pass
                
                volumes.append((rw_loc_val,"rprivate,z"))

            variable_params.append((rw_loc_id,rw_loc_val))
        
        # Assembling the command line    
        validation_params = []
        validation_params.extend(validation_cmd_pre_vol)
        
        for volume_dir,volume_mode in volumes:
            validation_params.append("-v")
            validation_params.append(volume_dir+':'+volume_dir+':'+volume_mode)
        
        validation_params_resume = [ *validation_params ]

        validation_params.extend(validation_cmd_post_vol)
        validation_params_resume.extend(validation_cmd_post_vol_resume)
        
        # Last, but not the least important
        # put the parameters in a file
        validation_params_dict = {}
        leaves = []
        for param_id,param_val in variable_params:
            node = validation_params_dict
            splitted_path = param_id.split('.')
            for step in splitted_path[:-1]:
                node = node.setdefault(step,{})
            
            param_key = splitted_path[-1]
            add_to_leaves = param_key not in node
            node.setdefault(param_key, []).append(param_val)
            if add_to_leaves:
                leaves.append((node, param_key))
        
        # Postprocessing of leaves, so single elements are not represented as arrays
        for node, param_key in leaves:
            if len(node[param_key]) == 1:
                node[param_key] = node[param_key][0]
        
        params_file = os.path.join(workdir, 'params-file.json')
        with open(params_file, mode="w", encoding="utf-8") as pF:
            json.dump(validation_params_dict, pF, indent=4)
        validation_params_flags = [ "-params-file", params_file ]
        
        validation_params.extend(validation_params_flags)
        validation_params_resume.extend(validation_params_flags)
        
        # Retries system was introduced because an insidious
        # bug happens sometimes
        # https://forums.docker.com/t/any-known-problems-with-symlinks-on-bind-mounts/32138
        retries = self.max_retries
        retval = -1
        validation_params_cmd = validation_params
        while retries > 0 and retval != 0:
            logger.debug('"'+'" "'.join(validation_params_cmd)+'"')
            sys.stdout.flush()
            sys.stderr.flush()
            
            retval = subprocess.call(validation_params_cmd,stdout=sys.stdout,stderr=sys.stderr)
            if retval != 0:
                retries -= 1
                logger.debug("\nFailed with {} , left {} tries\n".format(retval,retries))
                validation_params_cmd = validation_params_resume

        
        try:
            if retval == 0:
                # These state files are not needed when it has worked
                shutil.rmtree(os.path.join(workdir,'work'),True)
                # The workflow snapshot is removed
                if not replay_workflow:
                    os.unlink(dest_workflow_archive)
            else:
                logger.fatal("ERROR: VRE NF evaluation failed. Exit value: "+str(retval))

            # Nextflow workdir is saved for further analysis
            self.packDir(workdir,dest_workdir_archive,basePackdir='nextflow-workdir')
                
            shutil.rmtree(workdir,True)
        except:
            if retval == 0:
                retval = 127
        
        return retval == 0

    def run(self, input_files, input_metadata, output_files, output_metadata):
        """
        The main function to run the compute_metrics tool

        Parameters
        ----------
        input_files : dict
            List of input files - In this case there are no input files required
        input_metadata: dict
            Matching metadata for each of the files, plus any additional data
        output_files : dict
            List of the output files that are to be generated

        Returns
        -------
        output_files : dict
            List of files with a single entry.
        output_metadata : dict
            List of matching metadata for the returned files
        """
        
        
        logger.warning("Output files")
        logger.warning("{0}",json.dumps(output_files, indent=4))
        logger.warning("Output metadata")
        logger.warning("{0}",json.dumps(output_metadata, indent=4))

        # This one should be used to resolve relative inputs
        # (a relative project path is resolved against config dirname)
        project_path = self.configuration.get('project','.')
        if not os.path.isabs(project_path):
            project_path = os.path.normpath(os.path.join(self.config_dir, project_path))
        # This one should be used to resolve relative outputs
        # (a relative execution path is resolved against working directory)
        execution_path = os.path.abspath(self.configuration.get('execution', '.'))

        for key in output_files.keys():
            if key not in self.MASKED_OUT_KEYS:
                if output_files[key] is not None:
                    pop_output_path = output_files[key]
                    if not os.path.isabs(output_files[key]):
                        pop_output_path = os.path.normpath(os.path.join(execution_path, output_files[key]))
                else:
                    pop_output_path = os.path.join(execution_path, uuid.uuid4().hex + '.out')
                
                # Ensuring the parent directory already exists
                pop_output_parent_dir = os.path.dirname(pop_output_path)
                if not os.path.isdir(pop_output_parent_dir):
                    os.makedirs(pop_output_parent_dir)
                
                self.populable_outputs[key] = pop_output_path
                output_files[key] = pop_output_path
        
        participant_id = self.configuration['participant_id']
        unique_results_dir = participant_id + '_' + self.timestamp_str
        
        # Output parameter
        metrics_path = output_files.get("metrics")
        if metrics_path is None:
            metrics_path = os.path.join(execution_path, participant_id+'.json')
        if not os.path.isabs(metrics_path):
            metrics_path = os.path.normpath(os.path.join(execution_path, metrics_path))
        output_files['metrics'] = metrics_path
        
        # Output parameter
        tar_view_path = output_files.get("tar_view")
        if tar_view_path is None:
            tar_view_path = os.path.join(execution_path, unique_results_dir+'.tar.gz')
        if not os.path.isabs(tar_view_path):
            tar_view_path = os.path.normpath(os.path.join(execution_path, tar_view_path))
        output_files['tar_view'] = tar_view_path
        
        # Output parameter
        tar_nf_stats_path = output_files.get("tar_nf_stats")
        if tar_nf_stats_path is None:
            tar_nf_stats_path = os.path.join(execution_path, 'nfstats.tar.gz')
        if not os.path.isabs(tar_nf_stats_path):
            tar_nf_stats_path = os.path.normpath(os.path.join(execution_path, tar_nf_stats_path))
        output_files['tar_nf_stats'] = tar_nf_stats_path
        
        # Output parameter
        tar_other_path = output_files.get("tar_other")
        if tar_other_path is None:
            tar_other_path = os.path.join(execution_path, 'other_files.tar.gz')
        if not os.path.isabs(tar_other_path):
            tar_other_path = os.path.normpath(os.path.join(execution_path, tar_other_path))
        output_files['tar_other'] = tar_other_path
        
        # Output parameter
        dest_workflow_archive = output_files.get("workflow_archive")
        if dest_workflow_archive is None:
            dest_workflow_archive = os.path.join(execution_path, '.workflow.tar.gz')
        if not os.path.isabs(dest_workflow_archive):
            dest_workflow_archive = os.path.normpath(os.path.join(execution_path, dest_workflow_archive))
        
        # Defining the output directories
        results_path = os.path.join(execution_path, 'results')
        stats_path = os.path.join(execution_path, 'nf_stats')
        other_path = os.path.join(execution_path, 'other_files')
        
        results = self.validate_and_assess(
            input_files,
            results_path,
            stats_path,
            other_path,
            dest_workflow_archive
        )
        results = compss_wait_on(results)
        
        if results is False:
            logger.fatal("VRE NF RUNNER pipeline failed. See logs")
            raise Exception("VRE NF RUNNER pipeline failed. See logs")
            return {}, {}
       
        # Preparing the tar files
        if os.path.exists(results_path):
            self.packDir(results_path,tar_view_path,unique_results_dir)
            # Redoing metrics path
            for metrics_file in os.listdir(results_path):
                if metrics_file.startswith(participant_id) and metrics_file.endswith(".json"):
                    orig_metrics_path = os.path.join(results_path,metrics_file)
                    shutil.copyfile(orig_metrics_path,metrics_path)
                    break
        
        # Preparing the expected outputs
        if os.path.exists(stats_path):
            self.packDir(stats_path,tar_nf_stats_path,'nextflow-stats')
       
        input__metadata = input_metadata["input"]
        if isinstance(input__metadata, list):
            # Assuming it is a two list element
            input__metadata = input__metadata[1]
        assert isinstance(input__metadata, Metadata), "Mismatch between OpenVRE library and implementation"
        input__file_path = input__metadata.file_path
        # Initializing
        images_file_paths = []
        images_metadata = {
            'report_images': Metadata(
                # These ones are already known by the platform
                # so comment them by now
                data_type="report_image",
                file_type="IMG",
                file_path=images_file_paths,
                # Reference and golden data set paths should also be here
                sources=[input__file_path],
                meta_data={
                    "runner": "VRE_NF_RUNNER"
                }
            )
        }
        output_files['report_images'] = images_file_paths
        
        if os.path.exists(other_path):
            self.packDir(other_path,tar_other_path,'other_'+unique_results_dir)
            # Searching for image-like files
            for other_root, other_dirs, other_files in os.walk(other_path):
                for other_file in other_files:
                    theFileType = other_file[other_file.rindex(".")+1:].lower()
                    if theFileType in self.IMG_FILE_TYPES:
                        orig_file_path = os.path.join(other_root, other_file)
                        new_file_path = os.path.join(execution_path, other_file)
                        shutil.copyfile(orig_file_path, new_file_path)
                        
                        # Populating
                        images_file_paths.append(new_file_path)
        
        # BEWARE: Order DOES MATTER when there is a dependency from one output on another
        output_metadata_ret = {
            "metrics": Metadata(
                # These ones are already known by the platform
                # so comment them by now
                data_type="assessment",
                file_type="JSON",
                file_path=metrics_path,
                # Reference and golden data set paths should also be here
                sources=[input__file_path],
                meta_data={
                    "runner": "VRE_NF_RUNNER"
                }
            ),
            "tar_view": Metadata(
                # These ones are already known by the platform
                # so comment them by now
                data_type="tool_statistics",
                file_type="TAR",
                file_path=tar_view_path,
                # Reference and golden data set paths should also be here
                sources=[input__file_path],
                meta_data={
                    "runner": "VRE_NF_RUNNER"
                }
            ),
            "tar_nf_stats": Metadata(
                # These ones are already known by the platform
                # so comment them by now
                data_type="workflow_stats",
                file_type="TAR",
                file_path=tar_nf_stats_path,
                # Reference and golden data set paths should also be here
                sources=[input__file_path],
                meta_data={
                    "runner": "VRE_NF_RUNNER"
                }
            ),
            "tar_other": Metadata(
                # These ones are already known by the platform
                # so comment them by now
                data_type="other",
                file_type="TAR",
                file_path=tar_other_path,
                # Reference and golden data set paths should also be here
                sources=[input__file_path],
                meta_data={
                    "runner": "VRE_NF_RUNNER"
                }
            )
        }

        if os.path.exists(dest_workflow_archive):
            output_files['workflow_archive'] = dest_workflow_archive
            output_metadata_ret['workflow_archive'] = Metadata(
                data_type="file",
                file_type="TAR",
                file_path=dest_workflow_archive,
                meta_data={
                    "runner": "VRE_NF_RUNNER",
                    "visible": False
                }
            )
        
        # Adding the additional interesting files
        output_metadata_ret.update(images_metadata)
        
        # And adding "fake" entries for the other output files
        for pop_key, pop_path in self.populable_outputs.items():
            output_metadata_ret[pop_key] = Metadata(
                file_path = pop_path,
                sources=[input__file_path],
                meta_data={
                    "runner": "VRE_NF_RUNNER"
                }
            )
        
        return (output_files, output_metadata_ret)
