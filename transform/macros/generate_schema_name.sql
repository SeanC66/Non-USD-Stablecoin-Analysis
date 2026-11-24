{#
  Use the custom schema name as-is (e.g. "staging"), instead of dbt's default
  "<target_dataset>_staging". Datasets in this project are named by layer.

  Set DBT_DATASET_PREFIX to build into separate datasets instead, so a local
  build doesn't overwrite the production datasets the dashboard reads:
    DBT_DATASET_PREFIX=dev_ dbt build   ->  dev_seeds, dev_staging, dev_marts
  Sources still read the real `raw` dataset. CI and the daily run leave the
  variable unset, so production names are unchanged.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set prefix = env_var('DBT_DATASET_PREFIX', '') | trim -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ prefix }}{{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
