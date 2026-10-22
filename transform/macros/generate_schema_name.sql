{#
  Use the custom schema name as-is (e.g. "staging"), instead of dbt's default
  "<target_dataset>_staging". Datasets in this project are named by layer.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
