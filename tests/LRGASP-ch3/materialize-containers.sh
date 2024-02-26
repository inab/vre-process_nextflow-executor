#!/bin/sh

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
	set -e
}
trap cleanup EXIT ERR

cleanup
set -e

git_repo="$(jq -r '.arguments[] | select(.name=="nextflow_repo_uri") | .value' "${scriptdir}"/config.json)"
git_tag="$(jq -r '.arguments[] | select(.name=="nextflow_repo_tag") | .value' "${scriptdir}"/config.json)"

# Materialize the repo
git clone -n "${git_repo}" "${repodir}"
cd "${repodir}" && git checkout "${git_tag}"
bash materialize-containers.sh

docker images --format '{{json .}}' | jq -r 'select(.Repository | test("^lrgasp_")) | .Repository + ":" + .Tag' | while read localtag ; do
	docker tag ${localtag} liutiantian/${localtag}
done
if [ "$git_tag" = "ff5c8589a4f23b317630a5c77fc55d7b99b72c3f" ] ; then
	docker tag liutiantian/lrgasp_event2_validation:0.9.1 liutiantian/lrgasp_event2_validation:0.9.2
fi
