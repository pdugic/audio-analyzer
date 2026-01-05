#!/bin/sh
set -euo pipefail

# Validate presence and error clearly
if [ -z "$API_URL_INTERN" ] || [ -z "$API_GEN_URL_INTERN" ]; then
  [ -z "$API_URL_INTERN" ] && echo >&2 "ERROR: API_URL_INTERN environment variable is not set. Example: -e API_URL_INTERN='http://api:8080'"
  [ -z "$API_GEN_URL_INTERN" ] && echo >&2 "ERROR: API_GEN_URL_INTERN environment variable is not set. Example: -e API_GEN_URL_INTERN='http://gen:8000'"
  echo >&2 "Aborting container startup."
  exit 1
fi

# Path to served config file (present in image after COPY)
TEMPLATE_NGINX_CONF="/etc/nginx/conf.d/default.conf.template"
TARGET_NGINX_CONF="/etc/nginx/conf.d/default.conf"

# Create nginx conf from template if present
if [ -f "$TEMPLATE_NGINX_CONF" ]; then
  sed "s|\${API_URL_INTERN}|$API_URL_INTERN|g; s|\${API_GEN_URL_INTERN}|$API_GEN_URL_INTERN|g" "$TEMPLATE_NGINX_CONF" > "$TARGET_NGINX_CONF"
  echo "Wrote nginx conf to $TARGET_NGINX_CONF (API_URL_INTERN=$API_URL_INTERN, API_GEN_URL_INTERN=$API_GEN_URL_INTERN)"
else
  echo "Template $TEMPLATE_NGINX_CONF not found, leaving default nginx conf in place"
fi

# Require environment variables
API_URL="${API_URL:-}"
API_GEN_URL="${API_GEN_URL:-}"

# Validate presence and error clearly
if [ -z "$API_URL" ] || [ -z "$API_GEN_URL" ]; then
  [ -z "$API_URL" ] && echo >&2 "ERROR: API_URL environment variable is not set. Example: -e API_URL='http://api:8080'"
  [ -z "$API_GEN_URL" ] && echo >&2 "ERROR: API_GEN_URL environment variable is not set. Example: -e API_GEN_URL='http://gen:8000'"
  echo >&2 "Aborting container startup."
  exit 1
fi

# Also generate assets/config.json from template if present
TEMPLATE_CONFIG_JSON="/usr/share/nginx/html/browser/assets/config.json.template"
TARGET_CONFIG_JSON="/usr/share/nginx/html/browser/assets/config.json"
if [ -f "$TEMPLATE_CONFIG_JSON" ]; then
  sed "s|\${API_URL}|$API_URL|g; s|\${API_GEN_URL}|$API_GEN_URL|g" "$TEMPLATE_CONFIG_JSON" > "$TARGET_CONFIG_JSON"
  echo "Wrote app config to $TARGET_CONFIG_JSON (API_URL=$API_URL, API_GEN_URL=$API_GEN_URL)"
else
  echo "Template $TEMPLATE_CONFIG_JSON not found, leaving existing config.json in place"
fi

# Execute the original CMD
exec "$@"
