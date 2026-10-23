Real Exchange Rate Explorer
An interactive Streamlit app for an MBA international economics assignment. Compare any two countries (including the euro-area aggregate) using monthly International Monetary Fund (IMF) CPI and exchange-rate observations. Plot the nominal exchange rate, a real exchange-rate index, or both. Download the month-aligned data as CSV.
Economic definitions
Define Country 1 and Country 2 as selected in the sidebar.
S(t) = Country 2 currency units per unit of Country 1 currency.
E1(t) = Country 1 currency units per U.S. dollar (IMF monthly period average).
E2(t) = Country 2 currency units per U.S. dollar.
S(t) = E2(t) / E1(t). For USD as the local currency, use E = 1 by identity.
P1(t), P2(t) = monthly all-items CPI index levels for the two countries.
RER(t) = S(t) × P1(t) / P2(t).
RER* = arithmetic mean of RER(t) over valid months inside the user's currently selected sample.
Real Index(t) = 100 × RER(t) / RER*.
The valid-month mean of the Real Index is therefore 100 (up to floating-point precision). An index above 100 is above the chosen sample's average; it does not establish fundamental misvaluation. An increase in RER under the defined quotation convention means a real appreciation of Country 1's currency.
The nominal exchange rate is never rebased or normalized and is shown in actual Country 2 units per Country 1 unit. When plotting Both, it uses a separate y-axis from the index.
Important economic caveat: CPI is an index with an arbitrary statistical reference base. Two countries' IMF-reported CPIs may use different reference periods, meaning the absolute RER level and average depend on those bases. Relative movement and the selected-period normalized series are more informative than the unnormalized level. Different consumption baskets also mean this is not a directly measured relative international price level. The sample mean is a normalization benchmark, not a PPP fair-value estimate.
Data sources and API structure
All observations come from the public IMF SDMX 3.0 API. No paid subscription or API key is required under ordinary public access. The IMF may change accessibility or API conventions.
Source	Dataflow	SDMX key pattern	Notes
All-items CPI	`IMF.STA/CPI`	`{ISO3}.CPI._T.IX.M`	Five dimensions: country, index type, all items, index transformation, monthly
Monthly exchange rate	`IMF.STA/ER`	`{ISO3}.XDC_USD.PA_RT.M`	Four dimensions: country, LCU per USD, period-average rate, monthly
Euro area CPI	`IMF.STA/CPI`	`G163.HICP._T.IX.M`	Euro-area all-items HICP, not `G163.CPI_T.IX.M`
Euro area exchange rate	`IMF.STA/ER`	`G163.XDC_USD.PA_RT.M`	Euro area is an IMF aggregate, not a national ISO3 country
The full API data path follows `/data/dataflow/{agency}/{flow}/{version}/{key}`. This app uses `~` for the current flow version and a monthly `startPeriod`/`endPeriod` filter. It requests SDMX-CSV (`Accept: text/csv`) and parses the named columns `TIME_PERIOD`, `OBS_VALUE`, series dimensions and, where supplied, `SCALE`/`UNIT_MULT`. It checks returned indicator/frequency dimensions where available, rejects nonpositive CPI and rate observations, and applies reported scale exponents when unambiguous. A value like `2025-M03` is parsed as March 2025, not an annual observation. It does not substitute 1 for a missing U.S. CPI: the USD identity applies only to the USD exchange rate.
For historical series (where available), queries begin January 1976. Pre-euro and transitioning-currency history should not be assumed to represent a stable unchanged currency; users must interpret breaks in national currency definitions cautiously. IMF monthly `PA_RT` identifies a period-average exchange-rate quotation, not a yearly average; it is still a monthly observation.
The country dropdown starts from ISO-3166 names via `pycountry`, plus IMF Euro area `G163`. Some ISO countries lack compatible IMF histories and are flagged after selection, rather than silently supplied from outside datasets. The optional Check IMF country availability button makes lightweight IMF `lastNObservations=1` requests to discover places with both monthly indicators. This is a useful coverage hint, not a guarantee of complete history. Even when the check is unavailable, the normal dropdown and country-pair requests remain usable.
Missing observations
The application creates one row per selected calendar month. Missing/nonpositive/unavailable values remain `NaN`/blank and do not contribute to RER*. No interpolation or forward-filling is performed. Zero matching valid months produces a friendly message; missing countries or IMF outages return errors rather than fabricated data. A 24-hour Streamlit data cache avoids re-downloading country histories on each chart or sample-period change. The selected-period mean is calculated locally on each rerun.
References
IMF: Data APIs
IMF: CPI dataset
IMF: ER dataset
SDMX REST 3.0 data query specification
Example IMF CPI dimensions and actual key
Publish using GitHub's website — no local Python installation
Log in to github.com and click New repository (from the `+` menu).
Repository name: `real-exchange-rate-app`. Choose Public, select Add a README file if offered, and click Create repository.
In the repository, use Add file → Upload files. Upload `app.py`, `requirements.txt`, and `README.md` from the project package. If GitHub says README already exists, use its Edit control to paste the provided README instead, or delete the starter README first.
Ensure the files are in the repository root, not nested within an `rer_app/` folder; then click Commit changes.
Open Streamlit Community Cloud, sign in with GitHub and authorize repository access if prompted.
Click Create app / New app, choose Deploy a public app from GitHub, and select the repository `real-exchange-rate-app`, branch `main`, and entry point `app.py`.
Under Advanced settings, choose Python 3.12 if the Python version selector is offered. If it is unavailable, check Streamlit's current Python-runtime options; the dependencies are compatible with Python 3.12.
Click Deploy. Wait for Streamlit to install packages from `requirements.txt` and open the public app URL it generates.
Choose United States / Japan, start `2000-01`, and confirm the chart and CSV download work. Copy the app's share URL for your assignment.
Community Cloud options and button labels can change. Deployment is performed on the hosting service; no terminal, API key, `.streamlit/secrets.toml`, or local Python installation is required.
Troubleshooting
ModuleNotFoundError: Confirm `requirements.txt` is at the repository root and commits are saved. Reboot/redeploy the app.
404 or 400 from IMF: Verify the current dataflows (`IMF.STA/CPI` and `IMF.STA/ER`), their version, key dimension order, and country code at the IMF data portal. The IMF can revise its API or series availability.
IMF times out / 5xx: Refresh later or use another country pair. The app does not fall back to unrelated data providers.
No valid observations: Widen or shift the date range, select a better-covered economy, or inspect country coverage; the latest few months are often not published yet.
One currency seems reversed: Confirm `S=E2/E1`. USA → Japan should give JPY per USD; reversing the selection gives its reciprocal.
Values too large or odd: Check the CPI base years, metadata scale and selected-country currency transitions. CPI cannot be negative or zero. The nominal exchange rate is not indexed.
Can't select Python 3.12: Consult Streamlit deployment's Advanced settings or current supported runtimes. The app has no Python-version-specific native compilation requirement.
The app deploys but API requests fail: Use the Streamlit logs to inspect the HTTP/status message; corporate firewalls, IMF API changes, and blocked or temporarily unavailable endpoints can prevent retrieval.
Economic validation checklist
USA → JPN should show JPY per USD and its inverse when country order is reversed.
For identical countries and valid CPI data, S(t) = 1, RER(t) = 1, and index = 100 throughout.
Over all valid months, the arithmetic mean of the index should be 100.
Shorten the start/end period: RER* and the normalized index must recompute, while each month's nominal exchange rate stays unchanged.
Choose a period with limited data: missing rows should remain in CSV and not enter the mean.
Switch between Real, Nominal, Both: check independent axis labels and the reference line at 100.
Download the CSV and verify its month count and names.
Validation disclosure (October 22, 2026): The Python module, economic formula and CSV-parsing functions can be checked with synthetic local data. A live IMF API request and a deployed Streamlit session were not verified from the author's execution environment because external DNS/network access was blocked. Accordingly successful live operation is not guaranteed until steps 8–9 are completed. The IMF dataflow/schema choices are based on public SDMX documentation and recent implementation examples, not live responses retrieved by this environment.
