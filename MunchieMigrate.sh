#!/usr/bin/env bash
set -euo pipefail

: "${FORGEJO_URL:?FORGEJO_URL is required}"
: "${FORGEJO_TOKEN:?FORGEJO_TOKEN is required}"
: "${FORGEJO_OWNER:?FORGEJO_OWNER is required}"
: "${GITHUB_OWNER:?GITHUB_OWNER is required}"
: "${GITHUB_OWNER_TYPE:?GITHUB_OWNER_TYPE is required}"
: "${GITHUB_TOKEN:?GITHUB_TOKEN is required}"

MIRROR="${MIRROR:-true}"
MIGRATE_METADATA="${MIGRATE_METADATA:-true}"
DRY_RUN="${DRY_RUN:-1}"

# Compute API path for listing repos
if [[ "${GITHUB_OWNER_TYPE}" == "org" ]]; then
  OWNER_PATH="orgs"
else
  OWNER_PATH="users"
fi

# Use a temporary file to track processed repos and avoid duplicates
processed_repos="/tmp/processed_repos_$$"
> "${processed_repos}"

page=1
while :; do
  echo "Fetching ${GITHUB_OWNER} repos page ${page}..." >&2
  resp="$(curl -sfL \
    -H "Accept: application/vnd.github.v3+json" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    "https://api.github.com/${OWNER_PATH}/${GITHUB_OWNER}/repos?per_page=100&type=all&page=${page}")" || {
      echo "GitHub API error on page ${page}" >&2
      exit 1
  }

  count="$(jq 'length' <<<"${resp}")"
  [[ "${count}" -eq 0 ]] && break

  # Process each repo on this page
  jq -c '.[] | {name, private, clone_url}' <<<"${resp}" | while read -r repo; do
    name="$(jq -r '.name' <<<"${repo}")"
    
    # Skip if we've already processed this repo
    if grep -q "^${name}$" "${processed_repos}" 2>/dev/null; then
      echo "Skipping duplicate: ${name}" >&2
      continue
    fi
    
    # Mark as processed
    echo "${name}" >> "${processed_repos}"
    
    is_private="$(jq -r '.private' <<<"${repo}")"
    src_url="$(jq -r '.clone_url' <<<"${repo}")"

    # Build migration JSON payload (same as before)
    if [[ "${MIGRATE_METADATA}" == "true" ]]; then
      payload="$(jq -n \
        --arg src "${src_url}" \
        --arg repo "${name}" \
        --arg owner "${FORGEJO_OWNER}" \
        --arg token "${GITHUB_TOKEN}" \
        --argjson mirror "${MIRROR}" \
        --argjson private "${is_private}" \
        '{
          clone_addr: $src,
          repo_name: $repo,
          repo_owner: $owner,
          private: $private,
          mirror: $mirror,
          service: "github",
          auth_token: $token,
          wiki: true,
          issues: true,
          labels: true,
          milestones: true,
          pull_requests: true,
          releases: true
        }')"
    else
      payload="$(jq -n \
        --arg src "${src_url}" \
        --arg repo "${name}" \
        --arg owner "${FORGEJO_OWNER}" \
        --arg token "${GITHUB_TOKEN}" \
        --argjson mirror "${MIRROR}" \
        --argjson private "${is_private}" \
        '{
          clone_addr: $src,
          repo_name: $repo,
          repo_owner: $owner,
          private: $private,
          mirror: $mirror,
          service: "git",
          auth_token: $token
        }')"
    fi

    echo "Queueing migration: ${GITHUB_OWNER}/${name} -> ${FORGEJO_OWNER}/${name}" >&2

    if [[ "${DRY_RUN}" == "1" ]]; then
      echo "${payload}"
    else
      # Execute the migration
      http_code="$(curl -sS -o /tmp/migrate_out.$$ -w "%{http_code}" \
        -X POST "${FORGEJO_URL}/api/v1/repos/migrate" \
        -H "Authorization: token ${FORGEJO_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "${payload}")" || http_code="000"

      if [[ "${http_code}" != "201" && "${http_code}" != "202" ]]; then
        echo "Migration failed for ${name} (HTTP ${http_code}):" >&2
        sed -n '1,200p' /tmp/migrate_out.$$ >&2
      else
        echo "Migration queued for ${name} (HTTP ${http_code})" >&2
      fi
      rm -f /tmp/migrate_out.$$
    fi
  done

  page=$((page + 1))
done

# Cleanup
rm -f "${processed_repos}"
