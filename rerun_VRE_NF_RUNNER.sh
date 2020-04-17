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
		if [ -d "$TEST_DATA_DIR" ] ; then
			TEST_WORK_DIR="${BASEDIR}/${TESTNAME}-test"
			mkdir -p  "$TEST_WORK_DIR"
			# The relative directory does matter!
			cd "$BASEDIR"
			echo
			echo "INFO: Running test $TESTNAME"
			time "$TOOL_EXECUTABLE" --config "$TEST_DATA_DIR"/config.json --in_metadata "$TEST_DATA_DIR"/in_metadata.json --out_metadata "${TEST_WORK_DIR}/${TESTNAME}-out_metadata.json" --log_file "${TEST_WORK_DIR}/${TESTNAME}-test.log"
			echo
			echo "INFO: Test $TESTNAME return value $?"
		else
			eecho "Test set identifier $TESTNAME is invalid. Skipping..."
		fi
	done
else
	eecho "You must pass at least a test set identifier (i.e. the name of a directory in $TEST_BASE_DIR)" 
fi


