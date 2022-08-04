#!/bin/sh

DOCKER_TAG=2020.2.1

scriptdir="$(dirname "$0")"
case "$scriptdir" in
	/*)
		true
		;;
	.)
		scriptdir="$(pwd)"
		;;
	*)
		scriptdir="$(pwd)/${scriptdir}"
		;;
esac

repodir="${scriptdir}/the_repo"
cleanup() {
	set +e
	# This is needed in order to avoid
	# potential "permission denied" messages
	if [ -e "${repodir}" ] ; then
		chmod -R u+w "${repodir}"
		rm -rf "${repodir}"
	fi
}
trap cleanup EXIT ERR

cleanup
set -e

git_repo="$(jq -r '.arguments[] | select(.name=="nextflow_repo_uri") | .value' "${scriptdir}"/config.json)"
git_tag="$(jq -r '.arguments[] | select(.name=="nextflow_repo_tag") | .value' "${scriptdir}"/config.json)"
git clone -n "${git_repo}" "${repodir}"
cd "${repodir}" && git checkout "${git_tag}"
git submodule init && git submodule update
./build_dockers.bash "${DOCKER_TAG:-latest}"
