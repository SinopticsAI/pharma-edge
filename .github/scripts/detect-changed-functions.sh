#!/usr/bin/env bash
# Detects which cloud functions to deploy/validate based on git diff.
set -euo pipefail

MANIFEST="${GITHUB_WORKSPACE}/.github/functions-paths.json"
DEPLOY_ALL_PATHS=(
  ".github/functions-paths.json"
  ".github/workflows/detect-changes.yml"
  ".github/scripts/detect-changed-functions.sh"
  ".github/workflows/cd.yml"
  ".github/workflows/ci.yml"
  ".github/workflows/ct.yml"
  ".github/scripts/prepare-function-env.py"
  "infra/gateway/openapi.template.yaml"
  "scr/_shared"
)

echo "Diff range: ${DIFF_BASE}..${DIFF_HEAD}"

changed_files=$(git diff --name-only "${DIFF_BASE}" "${DIFF_HEAD}" || true)
changed_count=0
if [[ -n "$changed_files" ]]; then
  changed_count=$(printf '%s\n' "$changed_files" | grep -c . || true)
fi
echo "Changed files (${changed_count}):"
if [[ -n "$changed_files" ]]; then
  printf '%s\n' "$changed_files"
fi

force_deploy_all="${FORCE_DEPLOY_ALL:-false}"
deploy_all="${DEPLOY_ALL:-false}"

if [[ "$force_deploy_all" == "true" ]]; then
  deploy_all=true
fi

if [[ "${GITHUB_EVENT_NAME}" == "workflow_dispatch" ]] || [[ "${GITHUB_EVENT_NAME}" == "release" ]]; then
  deploy_all=true
fi

if [[ "$deploy_all" != "true" ]] && [[ -n "$changed_files" ]]; then
  for path in "${DEPLOY_ALL_PATHS[@]}"; do
    if printf '%s\n' "$changed_files" | grep -E "^${path}(/|$)" >/dev/null; then
      deploy_all=true
      echo "deploy_all=true reason: path ${path}"
      break
    fi
  done
fi

if [[ "$deploy_all" == "true" ]]; then
  ids=($(jq -r '.[].id' "$MANIFEST"))
else
  if [[ -z "$changed_files" ]]; then
    {
      echo "has_work=false"
      echo "deploy_all=false"
      echo "matrix<<EOF"
      echo '{"include":[]}'
      echo "EOF"
    } >> "$GITHUB_OUTPUT"
    exit 0
  fi

  declare -A selected=()
  while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    while IFS=$'\t' read -r id path; do
      if [[ "$file" == "$path"* ]]; then
        selected["$id"]=1
      fi
    done < <(jq -r '.[] | "\(.id)\t\(.path)"' "$MANIFEST")
  done <<< "$changed_files"

  if [[ ${#selected[@]} -eq 0 ]]; then
    {
      echo "has_work=false"
      echo "deploy_all=false"
      echo "matrix<<EOF"
      echo '{"include":[]}'
      echo "EOF"
    } >> "$GITHUB_OUTPUT"
    exit 0
  fi
  ids=("${!selected[@]}")
fi

mapfile -t ids < <(printf '%s\n' "${ids[@]}" | sort)
json_include=$(printf '%s\n' "${ids[@]}" | jq -R -s -c 'split("\n") | map(select(length>0)) | map({id:.})')
matrix="{\"include\":${json_include}}"

{
  echo "has_work=true"
  echo "deploy_all=${deploy_all}"
  echo "matrix<<EOF"
  echo "${matrix}"
  echo "EOF"
} >> "$GITHUB_OUTPUT"
echo "Selected functions (${#ids[@]}): ${ids[*]} (deploy_all=${deploy_all})"
