#!/bin/sh

DATA_RELEASE=2022

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

datasetsdir="${scriptdir}/reference_datasets"
inputsdir="${scriptdir}/input_dataset"

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
#rm -rf "${datasetsdir}" "${inputsdir}"

git_repo="$(jq -r '.arguments[] | select(.name=="nextflow_repo_uri") | .value' "${scriptdir}"/config.json)"
git_tag="$(jq -r '.arguments[] | select(.name=="nextflow_repo_tag") | .value' "${scriptdir}"/config.json)"
git clone -n "${git_repo}" "${repodir}"
cd "${repodir}" && git checkout "${git_tag}"

echo
echo "Fetching reference dataset for ${DATA_RELEASE}"
./fetch_reference_data.py --out-dir "${datasetsdir}" "${DATA_RELEASE}"

# Now, compute an input which will always work
echo
echo "Computing an input dataset which will always work with ${DATA_RELEASE}"
mkdir -p "$inputsdir"
gunzip -c "${scriptdir}"/data/input/SonicParanoid_default.rels.raw.gz | tr '\t' '\n' | sort -u > "$inputsdir"/input_ids.txt
sort -u "$inputsdir"/input_ids.txt > "$inputsdir"/input_ids-unique.txt
rm "$inputsdir"/input_ids.txt
gunzip -c "$datasetsdir"/mapping.json.gz | jq -r '.mapping | keys_unsorted[]' - | sort -u > "$inputsdir"/all-unique.txt
diff -u "$inputsdir"/input_ids-unique.txt "$inputsdir"/all-unique.txt | grep '^-[A-Z0-9]' | tr -d '-' > "$inputsdir"/input_ids-invalid.txt
rm "$inputsdir"/input_ids-unique.txt "$inputsdir"/all-unique.txt
zgrep -F -v -w -f "$inputsdir"/input_ids-invalid.txt "${scriptdir}"/data/input/SonicParanoid_default.rels.raw.gz | gzip -9c > "$inputsdir"/SonicParanoid_valid.rels.raw.gz
rm "$inputsdir"/input_ids-invalid.txt
cp -p "${repodir}"/example/oma-groups.orthoxml.gz "$inputsdir"
