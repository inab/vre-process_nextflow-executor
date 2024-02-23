#!/bin/sh

BUSCO_EUTHERIA_DATA_RELEASE=2024-01-08

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
datasetsdir="${scriptdir}/lrgasp-challenge-3_full_data"

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

input_handle="$(jq -r '.input_files[] | select(.name == "input") | .value' "${scriptdir}"/config.json)"
rel_input_path="$(jq -r --arg input_handle "$input_handle" '.[] | select(._id == $input_handle) | .file_path' "${scriptdir}"/in_metadata.json)"

# Materialize the repo
git clone -n "${git_repo}" "${repodir}"
cd "${repodir}" && git checkout "${git_tag}"

rm -rf "${datasetsdir}"
mv "${repodir}"/lrgasp-challenge-3_full_data "${datasetsdir}"

cd "${datasetsdir}"/public_ref
if [ -f "lrgasp_gencode_vM27_sirvs.gtf.gz" ] ; then
	echo "Uncompressing GENCODE reference dataset"
	gunzip lrgasp_gencode_vM27_sirvs.gtf.gz
fi

echo "Fetching LRGASP fasta"
curl -O https://lrgasp.s3.amazonaws.com/lrgasp_grcm39_sirvs.fasta

echo "Fetching BUSCO eutheria reference dataset ${BUSCO_EUTHERIA_DATA_RELEASE}"
mkdir -p busco_data/lineages
cd busco_data/lineages
curl -O https://busco-data.ezlab.org/v5/data/lineages/eutheria_odb10."${BUSCO_EUTHERIA_DATA_RELEASE}".tar.gz
tar xzf eutheria_odb10."${BUSCO_EUTHERIA_DATA_RELEASE}".tar.gz
rm eutheria_odb10."${BUSCO_EUTHERIA_DATA_RELEASE}".tar.gz

