# Point the QC pipeline (and `python -m demo --real`) at the local seminar
# retrieval stack from seminar/docker-compose.yml. Source it:
#
#   source seminar/env.sh
#
# Only local dummy credentials here. resources.yaml interpolates these three,
# so the production resource definitions are untouched.
export PG_DSN="postgresql://qc:qc-local@127.0.0.1:5435/qc_corpus"
export TRITON_EMBEDDING_URL="127.0.0.1:8011"
export TRITON_EMBEDDING_SSL="false"
