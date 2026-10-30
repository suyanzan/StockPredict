"""CSV input must not silently drop malformed stock-price observations."""

from datetime import date, timedelta

import pytest

from stockpredict.data import parse_csv


def csv_text(count=60, header="Date,Close", bad_row=None, reverse=False):
    rows = []
    for index in range(count):
        day = date(2025, 1, 1) + timedelta(days=index)
        rows.append(f"{day.isoformat()},{100 + index / 10}")
    if bad_row is not None:
        rows[20] = bad_row
    if reverse:
        rows.reverse()
    return header + "\n" + "\n".join(rows) + "\n"


def test_csv_accepts_case_insensitive_headers_bom_and_sorts_reverse_history():
    result = parse_csv(csv_text(header="\ufeffdate,cLoSe", reverse=True))
    assert len(result) == 60
    assert result[0] == {"date": "2025-01-01", "close": 100.0}
    assert result[-1]["close"] == pytest.approx(105.9)
    assert [point["date"] for point in result] == sorted(point["date"] for point in result)


@pytest.mark.parametrize(
    "bad_row",
    [
        "2025-01-21,0",
        "2025-01-21,-2.5",
        "2025-01-21,nan",
        "2025-01-21,inf",
        "2025-01-21,1e-10",
        "2025-01-21,1e13",
        "2025-01-21,not-a-number",
        "2025-01-21,",
        "2025-02-30,100",
        "yesterday,100",
        "20250121,100",
        "2025-01-01,100",  # duplicate of the first date
    ],
)
def test_csv_rejects_malformed_observations(bad_row):
    with pytest.raises(ValueError):
        parse_csv(csv_text(bad_row=bad_row))


@pytest.mark.parametrize("count", [0, 59, 5001])
def test_csv_enforces_minimum_and_maximum_observation_count(count):
    with pytest.raises(ValueError):
        parse_csv(csv_text(count=count))


@pytest.mark.parametrize("header", ["Date,Price", "Time,Close", "", "close"])
def test_csv_requires_date_and_close_columns(header):
    with pytest.raises(ValueError):
        parse_csv(csv_text(header=header))


def test_csv_rejects_duplicate_column_names_after_normalization():
    text = csv_text(header="Date,Close, CLOSE ")
    with pytest.raises(ValueError):
        parse_csv(text)


def test_csv_rejects_rows_with_more_columns_than_the_header():
    text = csv_text(bad_row="2025-01-21,102.0,unexpected")
    with pytest.raises(ValueError):
        parse_csv(text)


def test_csv_rejects_oversized_utf8_before_parsing():
    with pytest.raises(ValueError, match="2 MB"):
        parse_csv("中" * 700_000)
