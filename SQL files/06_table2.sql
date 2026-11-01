INSERT INTO public.table2 (
    id_column_2,
    integer_column_1,
    integer_column_2,
    text_column_1,
    integer_column_3,
    integer_column_4,
    integer_column_5,
    integer_column_6
)
SELECT
    main_row.id_column_1,
    position_data.position_number,
    ROUND(
        NULLIF(BTRIM(position_data.weight_text), '')::numeric * 1000
    )::integer,
    UPPER(BTRIM(position_data.type_text)),
    NULL::integer,
    NULL::integer,
    NULL::integer,
    CASE
        WHEN NULLIF(BTRIM(position_data.gap_text), '')::numeric > 0
        THEN ROUND(
            NULLIF(BTRIM(position_data.gap_text), '')::numeric * 1000
        )::integer
        ELSE NULL::integer
    END
FROM {{source}} AS source_row
CROSS JOIN LATERAL (VALUES
(1::smallint),
(2::smallint),
(3::smallint),
(4::smallint),
(5::smallint),
(6::smallint),
(7::smallint),
(8::smallint),
(9::smallint),
(10::smallint),
(11::smallint),
(12::smallint),
(13::smallint),
(14::smallint)
) AS ord(n)
CROSS JOIN LATERAL (
    SELECT
        ord.n::smallint AS position_number,
        (source_row.raw -> 'values') ->> ('integer_column_' || (ord.n + 1)::text) AS declared_number_text,
        (source_row.raw -> 'values') ->> ('text_column_' || (ord.n + 3)::text) AS type_text,
        (source_row.raw -> 'values') ->> ('numeric_column_' || (ord.n * 2 + 1)::text) AS weight_text,
        (source_row.raw -> 'values') ->> ('numeric_column_' || (ord.n * 2 + 2)::text) AS gap_text
) AS position_data
JOIN public.table1 AS main_row
  ON main_row.id_column_3 = source_row.raw_id
WHERE NULLIF(BTRIM(position_data.declared_number_text), '')::smallint
        = position_data.position_number
  AND NULLIF(BTRIM(position_data.weight_text), '')::numeric >= 0
  AND UPPER(BTRIM(position_data.type_text)) IN ('X', 'Y', 'Z');
