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

import sys
import os
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

class WF_RUNNER(Tool):
    """
    Tool for writing to a file
    """
    DEFAULT_NXF_IMAGE='nextflow/nextflow'
    DEFAULT_NXF_VERSION='19.04.1'
    DEFAULT_WF_BASEDIR='WF-checkouts'
    
    DEFAULT_DOCKER_CMD='docker'
    DEFAULT_GIT_CMD='git'
    
    MASKED_KEYS = { 'execution', 'project', 'description', 'nextflow_repo_uri', 'nextflow_repo_tag' }
    
    MASKED_OUT_KEYS = { 'metrics', 'tar_view', 'tar_nf_stats', 'tar_other' }
    
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
        Tool.__init__(self)

        self.timestamp_str = datetime.datetime.now().replace(microsecond=0).strftime("%Y%m%dT%H%M%S")
        
        local_config = configparser.ConfigParser()
        local_config.read(sys.argv[0] + '.ini')
        
        # Setup parameters
        self.nxf_image = local_config.get('nextflow','docker_image')  if local_config.has_option('nextflow','docker_image') else self.DEFAULT_NXF_IMAGE
        self.nxf_version = local_config.get('nextflow','version')  if local_config.has_option('nextflow','version') else self.DEFAULT_NXF_VERSION
        
        self.wf_basedir = os.path.abspath(os.path.expanduser(local_config.get('workflows','basedir')  if local_config.has_option('workflows','basedir') else self.DEFAULT_WF_BASEDIR))

        # Where the external commands should be located
        self.docker_cmd = local_config.get('defaults','docker_cmd')  if local_config.has_option('defaults','docker_cmd') else self.DEFAULT_DOCKER_CMD
        self.git_cmd = local_config.get('defaults','git_cmd')  if local_config.has_option('defaults','git_cmd') else self.DEFAULT_GIT_CMD
        
        if configuration is None:
            configuration = {}

        self.configuration.update(configuration)
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

    def doMaterializeRepo(self, git_uri, git_tag):
        repo_hashed_id = hashlib.sha1(git_uri).hexdigest()
        repo_hashed_tag_id = hashlib.sha1(git_tag).hexdigest()
        
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

        # Now, let's guess the repo and nextflow version
        nextflow_version = self.nxf_version
        try:
            with open(os.path.join(repo_tag_destdir,'nextcloud.config'),"r") as nc_config:
                pat = re.compile(r"nextflowVersion *= *([^ ]+)")
                for line in nc_config:
                    matched = pat.search(line)
                    if matched:
                        nextflow_version = matched.group(1)
                        break
        except:
            pass
 
        return repo_tag_destdir , nextflow_version
    
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
        with tarfile.open(destTarFile,mode='w:gz',bufsize=1024*1024) as tar:
                tar.add(resultsDir,arcname=basePackdir,recursive=True)
        

    @task(returns=bool, input_loc=FILE_IN, goldstandard_dir_loc=FILE_IN, assess_dir_loc=FILE_IN, public_ref_dir_loc=FILE_IN, results_loc=FILE_OUT, stats_loc=FILE_OUT, other_loc=FILE_OUT, isModifier=False)
    def validate_and_assess(self, input_loc, goldstandard_dir_loc, assess_dir_loc, public_ref_dir_loc, results_loc, stats_loc, other_loc):  # pylint: disable=no-self-use
        # First, we need to materialize the workflow
        nextflow_repo_uri = self.configuration.get('nextflow_repo_uri')
        nextflow_repo_tag = self.configuration.get('nextflow_repo_tag')
        
        if (nextflow_repo_uri is None) or (nextflow_repo_tag is None):
            logger.fatal("FATAL ERROR: both 'nextflow_repo_uri' and 'nextflow_repo_tag' parameters must be defined")
            return False
        
        # Checking out the repo to be used
        try:
            repo_dir , nextflow_version = self.doMaterializeRepo(nextflow_repo_uri,nextflow_repo_tag)
            logger.info("Fetched workflow: "+nextflow_repo_uri+" ("+nextflow_repo_tag+")")
            logger.info("Nextflow engine to be used: "+nextflow_version)
        except Exception as error:
            logger.fatal("While materializing repo: "+type(error).__name__ + ': '+str(error))
            return False
        
        # With the version, fetch the engine
        try:
            self.fetchNextflow(nextflow_version)
        except Exception as error:
            logger.fatal("While materializing Nextflow engine "+nextflow_version+": "+type(error).__name__ + ': '+str(error))
            return False
        
        challenges_ids = self.configuration['challenges_ids']
        participant_id = self.configuration['participant_id']
        
        inputDir = os.path.dirname(input_loc)
        inputBasename = os.path.basename(input_loc)
        
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
        
        dest_workdir_archive = os.path.join(os.path.abspath(self.configuration.get('project','.')),'nf-workdir.tar.gz')
        
        # Directories required by Nextflow in a Docker
        homedir = os.path.expanduser("~")
        nxf_assets_dir = os.path.join(workdir,".nextflow","assets")
        if not os.path.exists(nxf_assets_dir):
            try:
                os.makedirs(nxf_assets_dir)
            except Exception as error:
                logger.fatal("ERROR: Unable to create nextflow assets directory. Error: "+str(error))
                return False
        
        retval_stage = 'validation'
        
        # The fixed parameters
        validation_cmd_pre_vol = [
            "docker", "run", "--rm", "--net", "host",
            "-e", "USER",
            "-e", "NXF_DEBUG",
            "-e", "TZ="+tzstring,
            "-e", "HOME="+homedir,
            "-e", "NXF_ASSETS="+nxf_assets_dir,
            "-e", "NXF_USRMAP="+uid,
            "-e", "NXF_DOCKER_OPTS=-u "+uid+":"+gid+" -e HOME="+homedir+" -e TZ="+tzstring,
            "-v", "/var/run/docker.sock:/var/run/docker.sock"
        ]
        
        validation_cmd_post_vol = [
            "-w", workdir,
            self.nxf_image+":"+self.nxf_version,
            "nextflow", "run", repo_dir, "-profile", "docker"
        ]
        
        # This one will be filled in by the volume parameters passed to docker
        #docker_vol_params = []
        
        # This one will be filled in by the volume meta declarations, used
        # to generate the volume parameters
        volumes = [
            (homedir,"ro,Z"),
            (nxf_assets_dir,"Z"),
            (workdir,"Z"),
            (repo_dir,"ro,Z")
        ]
        
        # These are the parameters, including input and output files and directories
        
        # Parameters which are not input or output files are in the configuration
        variable_params = [
        #    ('challenges_ids',challenges_ids),
        #    ('participant_id',participant_id)
        ]
        for conf_key in self.configuration.keys():
            if conf_key not in self.MASKED_KEYS:
                variable_params.append((conf_key,self.configuration[conf_key]))
        
        
        variable_infile_params = [
            ('input',input_loc),
            ('goldstandard_dir',goldstandard_dir_loc),
            ('public_ref_dir',public_ref_dir_loc),
            ('assess_dir',assess_dir_loc)
        ]
        
        variable_outfile_params = [
            ('statsdir',stats_loc),
            ('outdir',results_loc),
            ('otherdir',other_loc)
        ]
        
        # The list of populable outputs
        variable_outfile_params.extend(self.populable_outputs.items())
        
        # Preparing the RO volumes
        for ro_loc_id,ro_loc_val in variable_infile_params:
            volumes.append((ro_loc_val,"ro,Z"))
            variable_params.append((ro_loc_id,ro_loc_val))
        
        # Preparing the RW volumes
        for rw_loc_id,rw_loc_val in variable_outfile_params:
            volumes.append((rw_loc_val,"Z"))
            variable_params.append((rw_loc_id,rw_loc_val))
        
        # Assembling the command line    
        validation_params = []
        validation_params.extend(validation_cmd_pre_vol)
        
        for volume_dir,volume_mode in volumes:
            validation_params.append("-v")
            validation_params.append(volume_dir+'/:'+volume_dir+'/:'+volume_mode)
        
        validation_params.extend(validation_cmd_post_vol)
        
        # Last, but not the least important
        for param_id,param_val in variable_params:
            validation_params.append("--" + param_id)
            validation_params.append(param_val)
        
        logger.debug(' '.join(validation_params))
        sys.stdout.flush()
        sys.stderr.flush()
        retval = subprocess.call(validation_params,stdout=sys.stdout,stderr=sys.stderr)
        
        if retval != 0:
            logger.fatal("ERROR: VRE NF evaluation failed. Exit value: "+str(retval))
        try:
            if retval == 0:
                # These state files are not needed when it has worked
                shutil.rmtree(os.path.join(workdir,'work'),True)
            self.packDir(workdir,dest_workdir_archive,basePackdir='nextflow-workdir')
            shutil.rmtree(workdir,True)
        except:
            if retval == 0:
                retval = 127
        
        return retval == 0

    def run(self, input_files, input_metadata, output_files):
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
        
        
        project_path = os.path.abspath(self.configuration.get('project','.'))
        for key in output_files.keys():
            if key not in self.MASKED_OUT_KEYS:
                if output_files[key] is not None:
                    pop_output_path = os.path.abspath(output_files[key])
                else:
                    pop_output_path = os.path.join(project_path,uuid.uuid4().hex + '.out')
                
                # Ensuring the parent directory already exists
                pop_output_parent_dir = os.path.dirname(pop_output_path)
                if not os.path.isdir(pop_output_parent_dir):
                    os.makedirs(pop_output_parent_dir)
                
                # Forcing the creation of the file
                with open(pop_output_path,mode="a") as pop_output_h:
                    pass
                self.populable_outputs[key] = pop_output_path
                output_files[key] = pop_output_path
        
        participant_id = self.configuration['participant_id']
        unique_results_dir = participant_id + '_' + self.timestamp_str
        
        metrics_path = output_files.get("metrics")
        if metrics_path is None:
            metrics_path = os.path.join(project_path,participant_id+'.json')
        metrics_path = os.path.abspath(metrics_path)
        output_files['metrics'] = metrics_path
        
        tar_view_path = output_files.get("tar_view")
        if tar_view_path is None:
            tar_view_path = os.path.join(project_path,unique_results_dir+'.tar.gz')
        tar_view_path = os.path.abspath(tar_view_path)
        output_files['tar_view'] = tar_view_path
        
        tar_nf_stats_path = output_files.get("tar_nf_stats")
        if tar_nf_stats_path is None:
            tar_nf_stats_path = os.path.join(project_path,'nfstats.tar.gz')
        tar_nf_stats_path = os.path.abspath(tar_nf_stats_path)
        output_files['tar_nf_stats'] = tar_nf_stats_path
        
        tar_other_path = output_files.get("tar_other")
        if tar_other_path is None:
            tar_other_path = os.path.join(project_path,'other_files.tar.gz')
        tar_other_path = os.path.abspath(tar_other_path)
        output_files['tar_other'] = tar_other_path
        
        # Defining the output directories
        results_path = os.path.join(project_path,'results')
        stats_path = os.path.join(project_path,'nf_stats')
        other_path = os.path.join(project_path,'other_files')
        
        # The directories are being created for the workflow manager, so they have the right owner
        os.makedirs(results_path)
        os.makedirs(stats_path)
        os.makedirs(other_path)
        
        results = self.validate_and_assess(
            os.path.abspath(input_files["input"]),
            os.path.abspath(input_files['goldstandard_dir']),
            os.path.abspath(input_files['assess_dir']),
            os.path.abspath(input_files['public_ref_dir']),
            results_path,
            stats_path,
            other_path
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
                sources=[input_metadata["input"].file_path],
                meta_data={
                    "tool": "VRE_NF_RUNNER"
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
                        orig_file_path = os.path.join(other_root,other_file)
                        new_file_path = os.path.join(project_path,other_file)
                        shutil.copyfile(orig_file_path,new_file_path)
                        
                        # Populating
                        images_file_paths.append(new_file_path)
        
        # BEWARE: Order DOES MATTER when there is a dependency from one output on another
        output_metadata = {
            "metrics": Metadata(
                # These ones are already known by the platform
                # so comment them by now
                data_type="assessment",
                file_type="JSON",
                file_path=metrics_path,
                # Reference and golden data set paths should also be here
                sources=[input_metadata["input"].file_path],
                meta_data={
                    "tool": "VRE_NF_RUNNER"
                }
            ),
            "tar_view": Metadata(
                # These ones are already known by the platform
                # so comment them by now
                data_type="tool_statistics",
                file_type="TAR",
                file_path=tar_view_path,
                # Reference and golden data set paths should also be here
                sources=[input_metadata["input"].file_path],
                meta_data={
                    "tool": "VRE_NF_RUNNER"
                }
            ),
            "tar_nf_stats": Metadata(
                # These ones are already known by the platform
                # so comment them by now
                data_type="tool_statistics",
                file_type="TAR",
                file_path=tar_nf_stats_path,
                # Reference and golden data set paths should also be here
                sources=[input_metadata["input"].file_path],
                meta_data={
                    "tool": "VRE_NF_RUNNER"
                }
            ),
            "tar_other": Metadata(
                # These ones are already known by the platform
                # so comment them by now
                data_type="tool_statistics",
                file_type="TAR",
                file_path=tar_other_path,
                # Reference and golden data set paths should also be here
                sources=[input_metadata["input"].file_path],
                meta_data={
                    "tool": "VRE_NF_RUNNER"
                }
            )
        }
        
        # Adding the additional interesting files
        output_metadata.update(images_metadata)
        
        # And adding "fake" entries for the other output files
        for pop_key, pop_path in self.populable_outputs.items():
            output_metadata[pop_key] = Metadata(
                file_path = pop_path,
                sources=[input_metadata["input"].file_path],
                meta_data={
                    "tool": "VRE_NF_RUNNER"
                }
            )
        
        return (output_files, output_metadata)
