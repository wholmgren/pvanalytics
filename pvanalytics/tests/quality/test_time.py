"""Tests for time-related quality control functions."""
from datetime import datetime
import pytz
import pytest
import pandas as pd
from pandas.tseries import frequencies
from pandas.util.testing import assert_series_equal
from pvanalytics.quality import time


@pytest.fixture
def times():
    """One hour in Mountain Standard Time at 10 minute intervals.

    Notes
    -----
    Copyright (c) 2019 SolarArbiter. See the file
    LICENSES/SOLARFORECASTARBITER_LICENSE at the top level directory
    of this distribution and at `<https://github.com/pvlib/
    pvanalytics/blob/master/LICENSES/SOLARFORECASTARBITER_LICENSE>`_
    for more information.

    """
    MST = pytz.timezone('MST')
    return pd.date_range(start=datetime(2018, 6, 15, 12, 0, 0, tzinfo=MST),
                         end=datetime(2018, 6, 15, 13, 0, 0, tzinfo=MST),
                         freq='10T')


def test_timestamp_spacing_date_range(times):
    """An index generated by pd.date_range has the expected spacing."""
    assert_series_equal(
        time.spacing(times, times.freq),
        pd.Series(True, index=times)
    )


def test_timestamp_spacing_one_timestamp(times):
    """An index with only one timestamp has uniform spacing."""
    assert_series_equal(
        time.spacing(times[[0]], times.freq),
        pd.Series(True, index=[times[0]])
    )


def test_timestamp_spacing_one_missing(times):
    """The timestamp following a missing timestamp will be marked False."""
    assert_series_equal(
        time.spacing(times[[0, 2, 3]], times.freq),
        pd.Series([True, False, True], index=times[[0, 2, 3]])
    )


def test_timestamp_spacing_too_frequent(times):
    """Timestamps with too high frequency will be marked False."""
    assert_series_equal(
        time.spacing(times, '30min'),
        pd.Series([True] + [False] * (len(times) - 1), index=times)
    )


@pytest.fixture(scope='module', params=['H', '15T', 'T'])
def midday(request, albuquerque):
    solar_position = albuquerque.get_solarposition(
        pd.date_range(
            start='1/1/2020', end='3/1/2020', closed='left',
            tz='MST', freq=request.param
        )
    )
    mid_day = (solar_position['zenith'] < 87).groupby(
        solar_position.index.date
    ).apply(
        lambda day: (day[day].index.min()
                     + ((day[day].index.max() - day[day].index.min()) / 2))
    )
    mid_day = mid_day.dt.hour * 60 + mid_day.dt.minute
    mid_day.index = pd.DatetimeIndex(mid_day.index, tz='MST')
    daytime = solar_position['zenith'] < 87
    daytime.index.freq = None
    return {'daytime': daytime,
            'clearsky_midday': mid_day}


def test_shift_ruptures_no_shift(midday):
    """Daytime mask with no time-shifts yields a series with 0s for
    shift amounts."""
    shifts = time.shifts_ruptures(
        midday['daytime'],
        midday['clearsky_midday']
    )
    assert_series_equal(
        shifts,
        pd.Series(0, index=midday['daytime'].index, dtype='int64'),
        check_names=False
    )


def test_shift_ruptures_positive_shift(midday):
    """Every day shifted 1 hour later yields a series with shift
     of 60 for each day."""
    shifted = _shift_between(
        midday['daytime'], 60,
        start='2020-01-01',
        end='2020-02-29'
    )
    assert_series_equal(
        time.shifts_ruptures(shifted, midday['clearsky_midday']),
        pd.Series(60, index=shifted.index, dtype='int64'),
        check_names=False
    )


def test_shift_ruptures_negative_shift(midday):
    shifted = _shift_between(
        midday['daytime'], -60,
        start='2020-01-01',
        end='2020-02-29'
    )
    assert_series_equal(
        time.shifts_ruptures(shifted, midday['clearsky_midday']),
        pd.Series(-60, index=shifted.index, dtype='int64'),
        check_names=False
    )


def test_shift_ruptures_partial_shift(midday):
    shifted = _shift_between(
        midday['daytime'], 60,
        start='2020-1-1', end='2020-2-1'
    )
    expected = pd.Series(60, index=midday['daytime'].index)
    expected.loc['2020-2-2':] = 0
    assert_series_equal(
        time.shifts_ruptures(shifted, midday['clearsky_midday']),
        expected,
        check_names=False
    )


def _shift_between(series, shift, start, end):
    freq_minutes = pd.to_timedelta(
        frequencies.to_offset(pd.infer_freq(series.index))
    ).seconds // 60
    before = series[:start]
    during = series[start:end]
    after = series[end:]
    during = during.shift(shift // freq_minutes, fill_value=False)
    shifted = before.append(during).append(after)
    return shifted[~shifted.index.duplicated()]


def test_shift_ruptures_period_min(midday):
    no_shifts = pd.Series(0, index=midday['daytime'].index, dtype='int64')
    assert_series_equal(
        time.shifts_ruptures(
            midday['daytime'], midday['clearsky_midday'],
            period_min=len(midday['clearsky_midday'])
        ),
        no_shifts,
        check_names=False
    )

    shifted = _shift_between(
        midday['daytime'], 60,
        start='2020-01-01',
        end='2020-01-20'
    )
    shift_expected = pd.Series(0, index=shifted.index, dtype='int64')
    shift_expected.loc['2020-01-01':'2020-01-20'] = 60
    assert_series_equal(
        time.shifts_ruptures(
            shifted, midday['clearsky_midday'], period_min=30
        ),
        no_shifts,
        check_names=False
    )
    assert_series_equal(
        time.shifts_ruptures(
            shifted, midday['clearsky_midday'], period_min=15
        ),
        shift_expected,
        check_names=False
    )

    with pytest.raises(ValueError):
        time.shifts_ruptures(
            midday['daytime'], midday['clearsky_midday'],
            period_min=10000
        )


def test_shifts_ruptures_shift_at_end(midday):
    shifted = _shift_between(
        midday['daytime'], 60,
        start='2020-02-01',
        end='2020-02-29'
    )
    shift_expected = pd.Series(0, index=shifted.index, dtype='int64')
    shift_expected['2020-02-02':'2020-02-29'] = 60
    shifts = time.shifts_ruptures(shifted, midday['clearsky_midday'])
    assert_series_equal(
        shifts,
        shift_expected,
        check_names=False
    )


def test_shifts_ruptures_shift_in_middle(midday):
    shifted = _shift_between(
        midday['daytime'], 60,
        start='2020-01-25',
        end='2020-02-15'
    )
    shift_expected = pd.Series(0, index=shifted.index, dtype='int64')
    shift_expected['2020-01-26':'2020-02-15'] = 60
    shifts = time.shifts_ruptures(shifted, midday['clearsky_midday'])
    assert_series_equal(
        shifts,
        shift_expected,
        check_names=False
    )


def test_shift_ruptures_shift_min(midday):
    shifted = _shift_between(
        midday['daytime'], 30,
        start='2020-01-01',
        end='2020-01-25',
    )
    shift_expected = pd.Series(0, index=shifted.index, dtype='int64')
    shift_expected.loc['2020-01-01':'2020-01-25'] = 30
    no_shift = pd.Series(0, index=shifted.index, dtype='int64')
    assert_series_equal(
        time.shifts_ruptures(
            shifted, midday['clearsky_midday'],
            shift_min=60, round_up_from=40
        ),
        no_shift,
        check_names=False
    )
    assert_series_equal(
        time.shifts_ruptures(
            shifted, midday['clearsky_midday'],
            shift_min=30
        ),
        shift_expected if pd.infer_freq(shifted.index) != 'H' else no_shift,
        check_names=False
    )


def test_rounding():
    xs = pd.Series(
        [-10, 10, -16, 16, -28, 28, -30, 30, -8, 8, -7, 7, -3, 3, 0]
    )
    assert_series_equal(
        time._round_multiple(xs, 15),
        pd.Series([-15, 15, -15, 15, -30, 30, -30, 30, -15, 15, 0, 0, 0, 0, 0])
    )
    assert_series_equal(
        time._round_multiple(xs, 15, up_from=9),
        pd.Series([-15, 15, -15, 15, -30, 30, -30, 30, 0, 0, 0, 0, 0, 0, 0])
    )
    assert_series_equal(
        time._round_multiple(xs, 15, up_from=15),
        pd.Series([0, 0, -15, 15, -15, 15, -30, 30, 0, 0, 0, 0, 0, 0, 0])
    )
    assert_series_equal(
        time._round_multiple(xs, 30),
        pd.Series([0, 0, -30, 30, -30, 30, -30, 30, 0, 0, 0, 0, 0, 0, 0])
    )
