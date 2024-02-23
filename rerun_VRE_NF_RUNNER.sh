#!/bin/bash

###
### Testing in a local installation
### the VRE server CMD
###
### * Automatically created by MuGVRE *
###
REALPATH="$(realpath "$0")"
BASEDIR="$(dirname "$REALPATH")"
case "$BASEDIR" in
	/*)
		true
		;;
	*)
		BASEDIR="${PWD}/$BASEDIR"
		;;
esac

eecho() {
	echo "ERROR: $@" 1>&2
}

TOOL_EXECUTABLE="${BASEDIR}/VRE_NF_RUNNER"
TEST_BASE_DIR="${BASEDIR}/tests"
if [ $# -gt  0 ] ; then
	for TESTNAME in "$@" ; do
		TEST_DATA_DIR="${TEST_BASE_DIR}/$TESTNAME"
		TEST_CONFIG_PATH="${TEST_DATA_DIR}"/config.json
		if [ -f "$TEST_CONFIG_PATH" ] ; then
			TEST_IN_METADATA_PATH="${TEST_DATA_DIR}"/in_metadata.json
			TEST_REL_WORK_DIR="$(jq -r '.arguments[] | select(.name == "execution") | .value' "$TEST_CONFIG_PATH")"
			if [ -z "$TEST_REL_WORK_DIR" ] ; then
				TEST_REL_WORK_DIR="test-results/${TESTNAME}"
			fi
			case "${TEST_REL_WORK_DIR}" in
				/*)
					# No absolute paths, please
					TEST_REL_WORK_DIR="${TEST_REL_WORK_DIR:1}"
					;;
			esac
			
			TEST_WORK_DIR="${BASEDIR}/${TEST_REL_WORK_DIR}"
			mkdir -p  "$TEST_WORK_DIR"
			
			# The working directory does matter for the relative output directory!
			echo
			echo "INFO: Running test $TESTNAME (results will be at $TEST_REL_WORK_DIR)"
			time "$TOOL_EXECUTABLE" --config "$TEST_CONFIG_PATH" --in_metadata "$TEST_IN_METADATA_PATH" --out_metadata "${TEST_WORK_DIR}/${TESTNAME}-out_metadata.json" --log_file "${TEST_WORK_DIR}/${TESTNAME}-test.log"
			echo
			echo "INFO: Test $TESTNAME return value $? (results at $TEST_REL_WORK_DIR)"
		else
			eecho "Test set identifier $TESTNAME is invalid (missing directory or config?). Skipping..."
		fi
	done
else
	eecho "You must pass at least a test set identifier (i.e. the name of a directory in $TEST_BASE_DIR)" 
fi


