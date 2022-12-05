#!/bin/sh

set -e

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
datasetsdir="${scriptdir}/TCGA_full_data"
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

git_repo="$(jq -r '.arguments[] | select(.name=="nextflow_repo_uri") | .value' "${scriptdir}"/config.json)"
git_tag="$(jq -r '.arguments[] | select(.name=="nextflow_repo_tag") | .value' "${scriptdir}"/config.json)"

# Materialize the repo
git clone -n "${git_repo}" "${repodir}"
cd "${repodir}" && git checkout "${git_tag}"

# Then, remove remnants of previous materialization
rm -rf "${datasetsdir}"
# And last, move the data directory
mv TCGA_sample_data "${datasetsdir}"

