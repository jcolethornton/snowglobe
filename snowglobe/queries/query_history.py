def get_warehouse_queries(days: int = 7) -> str:
    if days < 1 or days > 365:
        raise ValueError("days must be between 1 and 365")

    warehouse_queries = f"""
    SELECT
        query_id,
        user_name,
        warehouse_name,
        warehouse_size,
        query_text,
        query_tag,
        query_type,
        bytes_scanned,
        start_time,
        total_elapsed_time / 1000 AS execution_time_sec,
        POWER(
            2,
            CASE
                WHEN warehouse_size = 'X-Small' THEN 0
                WHEN warehouse_size = 'Small' THEN 1
                WHEN warehouse_size = 'Medium' THEN 2
                WHEN warehouse_size = 'Large' THEN 3
                WHEN warehouse_size = 'X-Large' THEN 4
                ELSE REGEXP_SUBSTR(warehouse_size, '\\d+') + 4
            END
        ) AS warehouse_multiplier,
        ROUND(
            execution_time_sec * warehouse_multiplier / 3600,
            2
        ) AS estimated_credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE 
        start_time >= DATEADD(day, -{days}, CURRENT_TIMESTAMP())
        and warehouse_size is not null
    """
    return warehouse_queries
