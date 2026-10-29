{% set _ = salt['omv_utils.register_jinja_filters']() %}

include:
  - .{{ salt['pillar.get']('deploy_h340', 'default') }}
