"""Real Exchange Rate Explorer — IMF SDMX 3.0, monthly CPI and FX.

Streamlit Community Cloud: Python 3.12; no API key or local files needed.
"""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pycountry
import requests
import streamlit as st


API_ROOT = "https://api.imf.org/external/sdmx/3.0"
EARLIEST = "1976-01"
CACHE_TTL = 24 * 60 * 60
CSV_ACCEPT = "text/csv"
EURO_AREA = "G163"

st.set_page_config(
    page_title="Real Exchange Rate Explorer",
    page_icon="🌐",
    layout="wide",
    initial_sidebar_state="expanded",
)


class IMFDataError(Exception):
    """Problem retrieving or interpreting IMF observations."""


def get_countries() -> dict[str, str]:
    """ISO-3166 names for UI; existence of IMF data checked on selection."""
    countries = {c.alpha_3: c.name for c in pycountry.countries}
    countries.update({
        "G163": "Euro area (IMF G163; HICP)",
        "USA": "United States",
        "JPN": "Japan",
        "GBR": "United Kingdom",
        "KOR": "South Korea",
        "TWN": "Taiwan",
    })
    return countries


COUNTRIES = get_countries()


def api_url(kind: str, country: str) -> tuple[str, str, str]:
    """Construct a FULL IMF SDMX 3.0 path, including flow and 4/5D key.

    Version '~' selects the latest dataflow version (no frozen version ID).
    IMF CPI dimensions: COUNTRY.INDEX_TYPE.COICOP_1999.TRANSFORMATION.FREQ.
    IMF ER dimensions: COUNTRY.INDICATOR.TRANSFORMATION.FREQ.
    """
    if not re.fullmatch(r"[A-Z0-9]{3,4}", country):
        raise IMFDataError(f"Invalid IMF geography code: {country!r}")
    if kind == "cpi":
        flow = "CPI"
        # G163 headline HICP is in the CPI flow (separate from national CPI).
        key = f"{country}.{'HICP' if country == EURO_AREA else 'CPI'}._T.IX.M"
    elif kind == "fx":
        flow = "ER"
        key = f"{country}.XDC_USD.PA_RT.M"
    else:
        raise ValueError(f"Unknown series type: {kind}")
    return f"{API_ROOT}/data/dataflow/IMF.STA/{flow}/~/{key}", flow, key


def get_csv(url: str, params: dict[str, Any]) -> pd.DataFrame:
    """Retrieve SDMX-CSV; never interpret a server error as actual data."""
    try:
        response = requests.get(
            url,
            params=params,
            headers={"Accept": CSV_ACCEPT, "User-Agent": "RealExchangeRateExplorer/1.0"},
            timeout=(10, 40),
        )
        response.raise_for_status()
    except requests.exceptions.Timeout as exc:
        raise IMFDataError("IMF request timed out. Retry after a moment.") from exc
    except requests.exceptions.RequestException as exc:
        raise IMFDataError(f"IMF request failed: {exc}") from exc

    if response.status_code == 204 or not response.content:
        return pd.DataFrame()
    content_type = response.headers.get("Content-Type", "").lower()
    if "html" in content_type or "json" in content_type or response.text.lstrip().startswith("<"):
        raise IMFDataError(
            f"IMF did not return CSV (Content-Type: {content_type or 'unknown'}). "
            "The endpoint or dataflow may have changed."
        )
    try:
        frame = pd.read_csv(io.StringIO(response.text), low_memory=False, dtype=str)
    except (ValueError, pd.errors.ParserError) as exc:
        raise IMFDataError("IMF response could not be parsed as SDMX-CSV.") from exc
    frame.columns = [c.strip().split(":")[0].upper() for c in frame.columns]
    if not frame.empty and not {"TIME_PERIOD", "OBS_VALUE"}.issubset(frame.columns):
        raise IMFDataError(
            "Unexpected IMF CSV columns. Expected TIME_PERIOD and OBS_VALUE; "
            f"received: {', '.join(frame.columns[:12])}."
        )
    return frame


def parse_month(value: Any) -> pd.Timestamp | None:
    """Accept IMF 2025-M01, 2025-01, or 2025-01-01; reject annual data."""
    text = str(value).strip()
    match = re.match(r"^(\d{4})-(?:M)?(0[1-9]|1[0-2])(?:-\d{2})?$", text)
    if not match:
        return None
    year, month = int(match[1]), int(match[2])
    return pd.Timestamp(year=year, month=month, day=1)


def parse_observations(frame: pd.DataFrame, kind: str, country: str) -> pd.Series:
    """Convert monthly IMF records into one numeric value per month.

    Dataflow/key dimensions are validated again against response columns to
    avoid accidentally accepting a different indicator or frequency.
    """
    empty = pd.Series(dtype="float64", name=kind)
    if frame.empty:
        return empty
    df = frame.copy()
    for field, expected in {
        "COUNTRY": country,
        "FREQUENCY": "M",
        "INDICATOR": "XDC_USD" if kind == "fx" else None,
        "INDEX_TYPE": "HICP" if country == EURO_AREA else "CPI" if kind == "cpi" else None,
        "COICOP_1999": "_T" if kind == "cpi" else None,
        "TYPE_OF_TRANSFORMATION": "PA_RT" if kind == "fx" else "IX",
    }.items():
        if expected is not None and field in df.columns:
            df = df[df[field].astype(str).str.strip().eq(expected)]
    if df.empty:
        return empty

    df["month"] = df["TIME_PERIOD"].map(parse_month)
    df = df[df["month"].notna()].copy()
    if df.empty:
        return empty

    df["value"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")

    # IMF SDMX scale is a power-of-ten exponent, normally 0 for these series.
    # If scale attributes are ambiguous, fail rather than silently mix units.
    scale_fields = [c for c in ("SCALE", "UNIT_MULT") if c in df.columns]
    if scale_fields:
        scales = []
        for col in scale_fields:
            s = pd.to_numeric(df[col].replace("", np.nan), errors="coerce")
            invalid = df[col].notna() & df[col].astype(str).str.strip().ne("") & s.isna()
            if invalid.any():
                raise IMFDataError(f"Unrecognized IMF {col} scale for {country}.")
            scales.append(s.fillna(0))
        if len(scales) == 2 and (scales[0] != 0).any() and (scales[1] != 0).any():
            if not scales[0].equals(scales[1]):
                raise IMFDataError(f"Conflicting scale metadata for {country}.")
        exponent = scales[0]
        if len(scales) == 2:
            exponent = exponent.where(exponent != 0, scales[1])
        if ((exponent < -12) | (exponent > 12)).any():
            raise IMFDataError(f"Implausible IMF scale exponent for {country}.")
        df["value"] = df["value"] * (10.0 ** exponent)

    df["value"] = df["value"].replace([np.inf, -np.inf], np.nan)
    df.loc[df["value"] <= 0, "value"] = np.nan
    # Duplicates are not silently averaged or replaced: conflicting editions
    # are an error; identical duplicate values are harmless.
    nonmissing = df.dropna(subset=["value"])
    conflicts = nonmissing.groupby("month")["value"].nunique(dropna=True)
    if (conflicts > 1).any():
        raise IMFDataError(f"Multiple conflicting IMF observations for {country} in the same month.")
    output = df.groupby("month")["value"].first().sort_index()
    output.name = kind
    return output.astype(float)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_series(kind: str, country: str) -> pd.Series:
    """Fetch full available history once per country/series, not per UI date."""
    if kind == "fx" and country == "USA":
        # USD per USD = 1 is an exact definition; handled by common calendar.
        return pd.Series(dtype="float64", name="fx")
    url, _, _ = api_url(kind, country)
    frame = get_csv(url, {"startPeriod": EARLIEST, "endPeriod": date.today().strftime("%Y-%m")})
    return parse_observations(frame, kind, country)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def discover_country_codes() -> set[str]:
    """Optionally discover IMF-reported current coverage without bulk history.

    Queries *each series once* for last observation; this is merely a selector
    hint, not proof of data coverage for any specific historical date range.
    """
    # Four/five dimensional wildcard keys, not an unscoped large download.
    cpi_frame = get_csv(
        f"{API_ROOT}/data/dataflow/IMF.STA/CPI/~/*.CPI._T.IX.M",
        {"lastNObservations": 1},
    )
    fx_frame = get_csv(
        f"{API_ROOT}/data/dataflow/IMF.STA/ER/~/*.XDC_USD.PA_RT.M",
        {"lastNObservations": 1},
    )
    cpi = set(cpi_frame.get("COUNTRY", pd.Series(dtype=str)).dropna())
    fx = set(fx_frame.get("COUNTRY", pd.Series(dtype=str)).dropna())
    valid = cpi & (fx | {"USA"})
    # Special case requires distinct HICP aggregate coverage.
    if EURO_AREA in fx:
        euro_frame = get_csv(
            f"{API_ROOT}/data/dataflow/IMF.STA/CPI/~/{EURO_AREA}.HICP._T.IX.M",
            {"lastNObservations": 1},
        )
        if not euro_frame.empty:
            valid.add(EURO_AREA)
    if not valid:
        raise IMFDataError("The IMF availability check returned no matching country codes.")
    return valid


def month_sequence(start: str, end: str) -> pd.DatetimeIndex:
    return pd.date_range(start=start, end=end, freq="MS")


def build_dataset(
    country1: str,
    country2: str,
    start: str,
    end: str,
    cpi1: pd.Series,
    cpi2: pd.Series,
    fx1: pd.Series,
    fx2: pd.Series,
) -> tuple[pd.DataFrame, float]:
    """Month-align CPI and FX, compute S, RER, sample mean and mean-100 index."""
    months = month_sequence(start, end)
    data = pd.DataFrame(index=months)
    data.index.name = "Month"
    data["CPI Country 1"] = cpi1.reindex(months)
    data["CPI Country 2"] = cpi2.reindex(months)
    data["Exchange Rate Country 1 (LCU per USD)"] = 1.0 if country1 == "USA" else fx1.reindex(months)
    data["Exchange Rate Country 2 (LCU per USD)"] = 1.0 if country2 == "USA" else fx2.reindex(months)

    for col in data.columns:
        data.loc[~np.isfinite(data[col]) | (data[col] <= 0), col] = np.nan

    e1 = data["Exchange Rate Country 1 (LCU per USD)"]
    e2 = data["Exchange Rate Country 2 (LCU per USD)"]
    s = e2 / e1
    data["Nominal Exchange Rate S (Country 2 per Country 1)"] = s.replace([np.inf, -np.inf], np.nan)
    data["RER"] = (data["Nominal Exchange Rate S (Country 2 per Country 1)"]
                   * data["CPI Country 1"] / data["CPI Country 2"])
    data["RER"] = data["RER"].replace([np.inf, -np.inf], np.nan)
    data.loc[data["RER"] <= 0, "RER"] = np.nan
    average = float(data["RER"].mean()) if data["RER"].notna().any() else float("nan")
    data["Real Exchange Rate Index (sample mean=100)"] = (
        100 * data["RER"] / average if np.isfinite(average) and average > 0 else np.nan
    )
    data["Selected-Period RER Average (RER*)"] = average if np.isfinite(average) else np.nan
    data.insert(0, "Country 1", country1)
    data.insert(1, "Country 2", country2)
    return data, average


def fmt(value: Any, decimals: int = 3) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{value:,.{decimals}f}"


def latest_valid(data: pd.DataFrame, column: str) -> tuple[pd.Timestamp | None, float]:
    s = data[column].dropna()
    if s.empty:
        return None, float("nan")
    return s.index[-1], float(s.iloc[-1])


def plot_exchange_rates(data: pd.DataFrame, view: str, country1: str, country2: str) -> go.Figure:
    nominal = "Nominal Exchange Rate S (Country 2 per Country 1)"
    real = "Real Exchange Rate Index (sample mean=100)"
    nominal_label = f"Country 2 currency units per 1 Country 1 currency unit ({country2}/{country1})"
    if view == "Both":
        fig = make_subplots(specs=[[{"secondary_y": True}]])
    else:
        fig = go.Figure()
    if view in ("Real", "Both"):
        trace = go.Scatter(
            x=data.index, y=data[real], mode="lines", name="Real index",
            line={"color": "#1565A7", "width": 2.4},
            hovertemplate="%{x|%b %Y}<br>Real index: %{y:,.2f}<extra></extra>",
            connectgaps=False,
        )
        if view == "Both":
            fig.add_trace(trace, secondary_y=False)
        else:
            fig.add_trace(trace)
        fig.add_hline(y=100, line_width=1, line_dash="dash", line_color="#8B94A3",
                      annotation_text="Selected-period mean = 100",
                      annotation_position="top left")
    if view in ("Nominal", "Both"):
        trace = go.Scatter(
            x=data.index, y=data[nominal], mode="lines", name="Nominal S(t)",
            line={"color": "#DA8740", "width": 2.2},
            hovertemplate="%{x|%b %Y}<br>Nominal S(t): %{y:,.5f}<extra></extra>",
            connectgaps=False,
        )
        if view == "Both":
            fig.add_trace(trace, secondary_y=True)
        else:
            fig.add_trace(trace)
    if view == "Both":
        fig.update_yaxes(title_text="Real exchange rate index (mean = 100)", secondary_y=False)
        fig.update_yaxes(title_text=nominal_label, secondary_y=True)
    elif view == "Real":
        fig.update_yaxes(title_text="Real exchange rate index (mean = 100)")
    else:
        fig.update_yaxes(title_text=nominal_label)
    fig.update_layout(
        title=f"{country1} vs. {country2} — {view.lower()} exchange rate",
        xaxis_title="Month", template="plotly_white", hovermode="x",
        height=500, margin={"t": 65, "b": 30, "l": 25, "r": 25},
        legend={"orientation": "h", "y": 1.08, "x": 0},
    )
    fig.update_xaxes(rangeslider_visible=False)
    return fig


def run() -> None:
    st.title("Real Exchange Rate Explorer")
    st.caption("Monthly IMF data · Consumer prices and bilateral exchange rates · Selected-period mean = 100")

    with st.sidebar:
        st.header("Compare countries")
        codes = sorted(COUNTRIES, key=lambda c: (COUNTRIES[c].lower(), c))
        if st.button("Check IMF country availability", use_container_width=True):
            with st.spinner("Checking IMF CPI and exchange-rate coverage…"):
                try:
                    st.session_state["imf_available_codes"] = discover_country_codes()
                    st.session_state["availability_error"] = ""
                except IMFDataError as exc:
                    st.session_state["availability_error"] = str(exc)
        if st.session_state.get("availability_error"):
            st.warning("IMF availability check unavailable: " + st.session_state["availability_error"])
        checked = st.session_state.get("imf_available_codes")
        if checked:
            use_filter = st.checkbox("Show only countries detected in IMF", value=False)
            if use_filter:
                covered = [c for c in codes if c in checked]
                if covered:
                    codes = covered
                else:
                    st.warning("No supported ISO-country codes were returned; showing the full list.")
            st.caption("IMF coverage check is a rough indication; historical availability is checked after selection.")
        label = lambda code: f"{COUNTRIES[code]} ({code})"
        initial1 = codes.index("USA") if "USA" in codes else 0
        initial2 = codes.index("JPN") if "JPN" in codes else min(1, len(codes) - 1)
        country1 = st.selectbox("Country 1", codes, index=initial1, format_func=label)
        country2 = st.selectbox("Country 2", codes, index=initial2, format_func=label)
        st.divider()
        st.header("Sample period")
        years = list(range(1976, date.today().year + 1))
        month_names = [date(2000, m, 1).strftime("%B") for m in range(1, 13)]
        sy = st.selectbox("Start year", years, index=years.index(2000))
        sm = st.selectbox("Start month", range(1, 13), index=0,
                          format_func=lambda m: month_names[m - 1])
        ey = st.selectbox("End year", years, index=years.index(date.today().year))
        em = st.selectbox("End month", range(1, 13), index=date.today().month - 1,
                          format_func=lambda m: month_names[m - 1])
        start, end = f"{sy:04d}-{sm:02d}", f"{ey:04d}-{em:02d}"
        view = st.radio("Chart series", ["Real", "Nominal", "Both"], horizontal=True)
        st.caption("Data: IMF CPI and Exchange Rates (ER), monthly. Cached for 24 hours.")

    if start > end:
        st.error("Start month must not be later than end month.")
        st.stop()
    if end > date.today().strftime("%Y-%m"):
        st.error("The end month cannot be in the future.")
        st.stop()
    try:
        with st.spinner("Retrieving available IMF monthly observations…"):
            cpi1 = load_series("cpi", country1)
            cpi2 = cpi1 if country1 == country2 else load_series("cpi", country2)
            fx1 = load_series("fx", country1)
            fx2 = fx1 if country1 == country2 else load_series("fx", country2)
    except IMFDataError as exc:
        st.error(f"IMF data could not be retrieved: {exc}")
        st.info("Try again, select another country, or check the IMF data portal/API status.")
        st.stop()

    data, average = build_dataset(country1, country2, start, end, cpi1, cpi2, fx1, fx2)
    valid = int(data["RER"].notna().sum())
    total = len(data)
    if not valid:
        st.warning(
            "No valid months contain both CPI series and both required exchange rates "
            "in this date range. Try different countries or dates."
        )
        st.caption(f"Months selected: {total} · Valid months: 0")
        incomplete = data.reset_index()
        incomplete["Month"] = incomplete["Month"].dt.strftime("%Y-%m")
        st.download_button(
            "Download incomplete monthly data (CSV)",
            data=incomplete.to_csv(index=False, na_rep="").encode("utf-8"),
            file_name=f"rer_{country1}_{country2}_{start}_{end}_incomplete.csv",
            mime="text/csv",
        )
        st.stop()

    st.subheader(f"{COUNTRIES[country1]} / {COUNTRIES[country2]}")
    st.caption(f"{start} to {end} · {valid:,} valid months out of {total:,} selected")
    latest_s_date, latest_s = latest_valid(data, "Nominal Exchange Rate S (Country 2 per Country 1)")
    latest_index_date, latest_index = latest_valid(data, "Real Exchange Rate Index (sample mean=100)")
    a, b, c, d = st.columns(4)
    a.metric("Valid monthly observations", f"{valid:,}", help="Months contributing to the selected-period mean")
    b.metric("Average RER (RER*)", fmt(average, 5), help="Average across valid months within the selected dates")
    c.metric("Latest nominal S(t)", fmt(latest_s, 5), help=f"Observed {latest_s_date:%b %Y}" if latest_s_date else None)
    d.metric("Latest real index", fmt(latest_index, 2), help=f"Observed {latest_index_date:%b %Y}" if latest_index_date else None)
    if valid < total:
        st.warning(f"{total - valid:,} selected month(s) have insufficient or invalid IMF data and are excluded from RER*.")
    st.plotly_chart(plot_exchange_rates(data, view, country1, country2), use_container_width=True)

    with st.expander("Economic methodology and interpretation", expanded=True):
        st.markdown(
            f"""
**Nominal exchange rate:** S(t) is units of **{country2} currency per 1 {country1} currency**.
If IMF publishes E1 and E2 in domestic-currency units per U.S. dollar,
then **S(t) = E2(t) / E1(t)**. For the U.S., USD/USD is exactly 1.

**Real exchange rate:** RER(t) = S(t) × CPI₁(t) / CPI₂(t).
The **real index** equals 100 × RER(t) / RER*, where RER* is the mean RER
for **valid months in the currently selected date range**. Its mean is 100.

A **higher RER** is a real appreciation of Country 1's currency under this convention:
Country 1's goods become relatively more expensive when expressed in Country 2's currency.
An index **above 100** means above its selected-period average, **not proof of fundamental overvaluation**.

**Important CPI limitation:** IMF-reported national CPI indexes can use different base/reference
periods. Therefore the *absolute RER level* (and RER*) is sensitive to CPI base choices;
relative movements and the normalized index are the principal comparison tools.
Euro area CPI uses IMF's harmonized all-items HICP series. No missing data are interpolated.
"""
        )

    output = data.reset_index()
    output["Month"] = output["Month"].dt.strftime("%Y-%m")
    csv = output.to_csv(index=False, na_rep="", float_format="%.10g").encode("utf-8")
    st.download_button(
        "Download monthly data and calculations (CSV)",
        data=csv,
        file_name=f"rer_{country1}_{country2}_{start}_{end}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    with st.expander("View monthly data"):
        st.dataframe(output, use_container_width=True, hide_index=True)
    st.caption(
        "Sources: IMF Consumer Price Index (CPI) and Exchange Rates (ER), SDMX 3.0 public API. "
        "Currency history and coverage vary by country. API responses cached for 24 hours."
    )


if __name__ == "__main__":
    run()
