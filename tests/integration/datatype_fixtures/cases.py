"""Declarative SQL fixtures; expressions are trusted test inputs, never user data."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TypeCase:
    table: str
    postgres_type: str
    values: tuple[str, ...]
    changed: str
    oracle_type: str | None = None
    oracle_values: tuple[str, ...] | None = None
    aggregate: bool = False
    support: str = "candidate"
    aggregate_preserved: bool = False
    null_mismatch: bool = False

    @property
    def paths(self):
        return (["oracle_postgres"] if self.oracle_type else []) + ["postgres_postgres"]


CASES = (
    TypeCase("dt_nulls", "NUMERIC(8,2)", ("1", "NULL", "3"), "NULL",
             "NUMBER(8,2)", aggregate=True, null_mismatch=True),
    TypeCase("dt_smallint", "SMALLINT", ("-32768", "32767", "0"), "1", aggregate=True),
    TypeCase("dt_integer", "INTEGER", ("-2147483648", "2147483647", "0"), "1", aggregate=True),
    TypeCase("dt_bigint", "BIGINT", ("-9223372036854775808", "9223372036854775807", "0"),
             "1", aggregate=True),
    TypeCase("dt_decimal", "NUMERIC(38,9)",
             ("99999999999999999999999999999.123456789", "-0.000000001", "0"), "0.000000002",
             "NUMBER(38,9)", aggregate=True),
    TypeCase("dt_integral", "NUMERIC(18,0)",
             ("-999999999999999999", "999999999999999999", "0"), "1",
             "NUMBER(18,0)", aggregate=True),
    TypeCase("dt_scale", "NUMERIC(8,4)", ("1.23445", "-1.23445", "0.0001"), "0.0002",
             "NUMBER(8,4)", aggregate=True),
    TypeCase("dt_swap", "NUMERIC(8,2)", ("10", "20", "30"), "30",
             "NUMBER(8,2)", aggregate=True, aggregate_preserved=True),
    TypeCase("dt_real", "REAL", ("-1.5", "1.5", "0"), "0.5",
             "BINARY_FLOAT", aggregate=True),
    TypeCase("dt_double", "DOUBLE PRECISION", ("-1.25", "1.25", "0"), "0.25",
             "BINARY_DOUBLE", aggregate=True),
    TypeCase("dt_special_float", "DOUBLE PRECISION",
             ("'NaN'::float8", "'Infinity'::float8", "'-Infinity'::float8"), "0", aggregate=True),
    TypeCase("dt_unicode", "VARCHAR(80)",
             ("U&'caf\\00E9'", "U&'\\4F60\\597D \\+01F600'", "' leading and trailing '"),
             "'changed'", "VARCHAR2(80 CHAR)",
             ("UNISTR('caf\\00E9')", "UNISTR('\\4F60\\597D \\D83D\\DE00')",
              "' leading and trailing '")),
    TypeCase("dt_national", "VARCHAR(80)",
             ("U&'\\03A9'", "U&'\\65E5\\672C'", "'abc'"), "'changed'", "NVARCHAR2(80)",
             ("UNISTR('\\03A9')", "UNISTR('\\65E5\\672C')", "N'abc'")),
    TypeCase("dt_char", "CHAR(8)", ("'A'", "'AB  '", "'12345678'"), "'changed'", "CHAR(8 CHAR)"),
    TypeCase("dt_text", "TEXT", ("'hello'", "repeat('x', 10000)", "'last'"), "'changed'",
             "CLOB", ("TO_CLOB('hello')",
                      "TO_CLOB(RPAD('x', 4000, 'x')) || RPAD('x', 4000, 'x') || RPAD('x', 2000, 'x')",
                      "TO_CLOB('last')")),
    TypeCase("dt_nclob", "TEXT", ("U&'\\4F60\\597D'", "'second'", "'last'"), "'changed'",
             "NCLOB", ("TO_NCLOB(UNISTR('\\4F60\\597D'))", "TO_NCLOB('second')", "TO_NCLOB('last')")),
    TypeCase("dt_binary", "BYTEA", ("decode('00ff10', 'hex')", "decode('abcd', 'hex')",
             "decode('01', 'hex')"), "decode('02', 'hex')", "BLOB",
             ("TO_BLOB(HEXTORAW('00ff10'))", "TO_BLOB(HEXTORAW('abcd'))", "TO_BLOB(HEXTORAW('01'))")),
    TypeCase("dt_empty", "TEXT", ("''", "' '", "'x'"), "'y'"),
    TypeCase("dt_empty_binary", "BYTEA", ("decode('', 'hex')", "decode('00', 'hex')",
             "decode(repeat('ff', 10000), 'hex')"), "decode('01', 'hex')"),
    TypeCase("dt_date", "DATE", ("DATE '1900-01-01'", "DATE '2000-02-29'", "DATE '2099-12-31'"),
             "DATE '2099-12-30'"),
    TypeCase("dt_oracle_date", "TIMESTAMP(0)",
             ("TIMESTAMP '2000-02-29 12:34:56'", "TIMESTAMP '1900-01-01 00:00:00'",
              "TIMESTAMP '2099-12-31 23:59:59'"), "TIMESTAMP '2099-12-31 23:59:58'", "DATE",
             ("TO_DATE('2000-02-29 12:34:56','YYYY-MM-DD HH24:MI:SS')", "DATE '1900-01-01'",
              "TO_DATE('2099-12-31 23:59:59','YYYY-MM-DD HH24:MI:SS')")),
    TypeCase("dt_timestamp", "TIMESTAMP(6)",
             ("TIMESTAMP '2000-02-29 12:34:56.123456'", "TIMESTAMP '1970-01-01 00:00:00'",
              "TIMESTAMP '2024-03-10 01:59:59.999999'"), "TIMESTAMP '2024-03-10 02:00:00'", "TIMESTAMP(6)"),
    TypeCase("dt_timestamptz", "TIMESTAMP(6) WITH TIME ZONE",
             ("TIMESTAMPTZ '2024-11-03 01:30:00-04:00'", "TIMESTAMPTZ '2024-11-03 01:30:00-05:00'",
              "TIMESTAMPTZ '2024-03-10 07:00:00+00:00'"), "TIMESTAMPTZ '2024-03-10 07:00:01+00:00'",
             "TIMESTAMP(6) WITH TIME ZONE",
             ("TO_TIMESTAMP_TZ('2024-11-03 05:30:00 +00:00','YYYY-MM-DD HH24:MI:SS TZH:TZM')",
              "TO_TIMESTAMP_TZ('2024-11-03 06:30:00 +00:00','YYYY-MM-DD HH24:MI:SS TZH:TZM')",
              "TO_TIMESTAMP_TZ('2024-03-10 07:00:00 +00:00','YYYY-MM-DD HH24:MI:SS TZH:TZM')")),
    TypeCase("dt_time", "TIME(6)", ("TIME '00:00:00'", "TIME '12:34:56.123456'",
             "TIME '23:59:59.999999'"), "TIME '23:59:58'"),
    TypeCase("dt_interval", "INTERVAL", ("INTERVAL '1 day 02:03:04'", "INTERVAL '-1 second'",
             "INTERVAL '0 seconds'"), "INTERVAL '1 second'"),
    TypeCase("dt_boolean", "BOOLEAN", ("TRUE", "FALSE", "TRUE"), "FALSE"),
    TypeCase("dt_uuid", "UUID", ("'00000000-0000-0000-0000-000000000000'",
             "'ffffffff-ffff-ffff-ffff-ffffffffffff'", "'12345678-1234-1234-1234-123456789abc'"),
             "'12345678-1234-1234-1234-123456789abd'"),
    TypeCase("dt_json", "JSON", ("'{\"a\":1,\"b\":[true,null,\"text\"]}'", "'null'",
             "'{\"nested\":{\"value\":2}}'"), "'{\"nested\":{\"value\":3}}'"),
    TypeCase("dt_jsonb", "JSONB", ("'{\"a\":1,\"b\":[true,null]}'", "'null'",
             "'[1,2,3]'"), "'[1,2,4]'"),
    TypeCase("dt_xml", "XML", ("'<root>one</root>'", "'<root/>'", "'<root>three</root>'"),
             "'<root>changed</root>'"),
    TypeCase("dt_domain", "dt_positive", ("0", "1", "999.99"), "999.98", aggregate=True),
    TypeCase("dt_array", "INTEGER[]", ("ARRAY[1,2]", "ARRAY[]::integer[]", "ARRAY[NULL,3]"),
             "ARRAY[NULL,4]", support="unsupported"),
    TypeCase("dt_enum", "dt_state", ("'new'", "'done'", "'new'"), "'done'", support="unsupported"),
    TypeCase("dt_timetz", "TIME WITH TIME ZONE", ("TIMETZ '12:00:00+00'", "TIMETZ '12:00:00+02'",
             "TIMETZ '00:00:00-05'"), "TIMETZ '00:00:01-05'", support="unsupported"),
)