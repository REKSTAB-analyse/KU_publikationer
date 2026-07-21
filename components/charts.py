import plotly.graph_objects as go

import colorsys
from matplotlib import colors as mcolors
import matplotlib.patheffects as pe
import textwrap
import pycountry
import math
import gettext as _gettext

from components.colors import ku_color_sequence, adjust_color
 
PLOTLY_CONFIG = {
    "toImageButtonOptions": {"format": "png", "scale": 3},
    "displaylogo": False,
}

_DOMAIN_COLORS = {
    "Life Sciences": "#901a1e",
    "Physical Sciences": "#122947",
    "Social Sciences": "#39641c",
    "Health Sciences": "#0a5963",
}

_INTRA_GAP = 0.6    # afstand mellem bars inden for samme klynge
_INTER_GAP = 1.1    # afstand mellem klynger
_BAR_WIDTH  = 0.45  # søjlebredde

_LEGEND_ROW_PX = 26
_LEGEND_GAP_PX = 65
_LEGEND_ITEMS_PER_ROW = 6

_ORG_DIM_LABELS = {"Fak": "Fakultet", "Inst": "Institut", "Stil": "Stillingsgruppe"}

def _wrap_label(text: str, width: int = 16) -> str:
    return "<br>".join(textwrap.wrap(str(text), width=width, break_long_words=False)) or str(text)

def compute_group_keys(y_labels: list) -> list | None:
    """
    Beregner klyngenøgle pr. y-label til brug i fig_hbar_stacked.
    Labels med ' | ' separator klynges efter det sidste segment (højeste niveau).
    Returnerer None hvis ingen labels er multi-niveau.
    """
    if not any("|" in str(lbl) for lbl in y_labels if lbl != "KU samlet"):
        return None
    
    result = []
    for lbl in y_labels:
        if lbl == "KU samlet":
            result.append("__ku__")
        else:
            parts = [p.strip() for p in str(lbl).split("|")]
            result.append(parts[-1] if len(parts) > 1 else "__single__")
    return result

def _n_levels(group_keys: list) -> int:
    for gk in group_keys:
        if isinstance(gk, tuple):
            return len(gk)
    return 0

def _divergence_depth(prev_key, curr_key, n_levels: int) -> int:
    if prev_key is None or curr_key is None:
        return n_levels
    if prev_key == curr_key:
        return 0
    if not (isinstance(prev_key, tuple) and isinstance(curr_key, tuple)) or len(prev_key) != len(curr_key):
        return n_levels
    for i, (p, c) in enumerate(zip(prev_key, curr_key)):
        if p != c:
            return n_levels - i
    return 0

def _gap_for_depth(depth: int, n_levels: int) -> float:
    if n_levels <= 0 or depth <= 0:
        return _INTRA_GAP
    frac = min(depth, n_levels) / n_levels
    return _INTRA_GAP + frac * (_INTER_GAP - _INTRA_GAP)

def _build_y_positions(y_labels: list, group_keys: list) -> tuple:
    """group_keys: liste af tuples (grovseste -> fineste niveau, fx (Fak, Inst)),
    eller sentinels som "__ku__"/"__single__" for særlige rækker."""
    n_levels = _n_levels(group_keys)
    positions = []
    y = 0.0
    prev_key = None

    for i, gk in enumerate(group_keys):
        if i == 0:
            y = 0.0
        else:
            depth = _divergence_depth(prev_key, gk, n_levels)
            y += _gap_for_depth(depth, n_levels)
        positions.append(y)
        prev_key = gk
    
    return positions, positions, y_labels

def fig_hbar_stacked(
    data: dict,
    order: list = None,
    colors: dict = None,
    labels: dict = None,
    title: str = "",
    xaxis_title: str = "Antal",
    mode: str = "antal",
    group_keys: list = None,
    legend_position: str = "bottom",
    pct_denominators: dict = None,   # NY: eksplicit nævner pr. y-værdi til pct-beregning
) -> go.Figure:
    if order is None:
        totals = {}
        for y_data in data.values():
            for k, n in y_data.items():
                totals[k] = totals.get(k, 0) + n
        order = sorted(totals, key=lambda k: -totals[k])

    if colors is None:
        palette = ku_color_sequence(len(order))
        colors = {k: palette[i] for i, k in enumerate(order)}

    if labels is None:
        labels = {k: str(k) if k else "Ikke registreret" for k in order}

    y_labels      = list(data.keys())
    use_positions = group_keys is not None and len(group_keys) == len(y_labels)

    if use_positions:
        y_pos, tick_pos, tick_labels = _build_y_positions(y_labels, group_keys)
        total_span = (y_pos[-1] - y_pos[0]) if len(y_pos) > 1 else 0
        height     = max(200, int(total_span * 55 + 150))
        bar_width  = _BAR_WIDTH
        yaxis_kwargs = dict(
            tickmode="array", tickvals=tick_pos, ticktext=tick_labels,
            autorange="reversed", showgrid=False, zeroline=False,
        )
    else:
        y_pos      = y_labels
        height     = max(160, len(y_labels) * 40 + 80)
        bar_width  = 0.75
        yaxis_kwargs = dict(autorange="reversed")

    fig = go.Figure()
    for key in order:
        x_vals, txt_vals = [], []
        for y in y_labels:
            n     = data[y].get(key, 0)
            total = (pct_denominators.get(y) if pct_denominators else None) or sum(data[y].values()) or 1
            pct   = round(100 * n / total, 1)
            if mode == "pct":
                x_vals.append(pct)
                txt_vals.append(f"{pct}%")
            elif mode == "rate":
                x_vals.append(round(n, 2))
                txt_vals.append(f"{n:.2f}")
            else:
                x_vals.append(n)
                txt_vals.append(f"{n:,}")

        if not any(x_vals):
            continue

        if mode == "rate":
            value_hover = "%{customdata[0]:.2f} publikationer pr. forfatter<br>"
        else:
            value_hover = "%{customdata[0]:,} publikationer<br>"

        fig.add_trace(go.Bar(
            name=labels.get(key, str(key)),
            x=x_vals, y=y_pos, orientation="h",
            marker=dict(color=colors.get(key, "#cccccc"), line=dict(color="white", width=1)),
            text=txt_vals, textposition="inside", insidetextanchor="middle",
            width=bar_width,
            customdata=[
                (data[y].get(key, 0),
                 round(100 * data[y].get(key, 0) / ((pct_denominators.get(y) if pct_denominators else None) or sum(data[y].values()) or 1), 1))
                for y in y_labels
            ],
            hovertemplate=(
                f"<b>{labels.get(key, key)}</b><br>"
                f"{value_hover}"
                "%{customdata[1]}%<extra></extra>"
            ),
        ))
            
    if legend_position == "right":
        legend_kwargs = dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02, traceorder="normal")
        margin = dict(t=50, b=60, l=10, r=220)
    else:
        legend_kwargs = dict(
            orientation="h", yanchor="top",
            y=-(_LEGEND_GAP_PX / height),
            xanchor="left", x=0, traceorder="normal",
        )
        margin = dict(t=50, b=80, l=10, r=10)

    fig.update_layout(
        barmode="stack",
        bargap=0.05,
        bargroupgap=0.0,
        height=height,
        margin=margin,
        title=dict(text=title, font=dict(size=14)),
        legend=legend_kwargs,
        xaxis=dict(
            title="Andel (%)" if mode == "pct" else ("Publikationer pr. forfatter" if mode == "rate" else xaxis_title),
            tickformat="," if mode == "antal" else (".2f" if mode == "rate" else ".0f"),
            range=[0, 100] if mode == "pct" else None,
        ),
        yaxis=dict(**yaxis_kwargs),
        plot_bgcolor="white",
    )
    return fig


def _hls_gradient(base_hex: str, n: int, spread: float = 0.15) -> list:
    """KU-tro farvegradient: n nuancer af base_hex."""
    r, g, b = mcolors.to_rgb(base_hex)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l_min = max(0.12, l - spread)
    l_max = min(0.82, l + spread)
    colors = []
    for i in range(n):
        t = i / (n - 1) if n > 1 else 0.5
        l_new = l_min + t * (l_max - l_min)
        r2, g2, b2 = colorsys.hls_to_rgb(h, l_new, s)
        colors.append(mcolors.to_hex((r2, g2, b2)))
    return colors


def _nest_org_rows(rows: list, dims: list) -> dict:
    """
    Grupperer rows rekursivt efter dims (grovseste -> fineste). Returnerer
    {key: {"total": n, "fak": <fakultet>, "children": {...} | None}}.
    """
    groups = {}
    for row in rows:
        key = row[dims[0]]
        groups.setdefault(key, []).append(row)
    result = {}
    for key, sub_rows in groups.items():
        total = sum(r["n"] for r in sub_rows)
        fak = sub_rows[0].get("Fak")
        children = _nest_org_rows(sub_rows, dims[1:]) if len(dims) > 1 else None
        result[key] = {"total": total, "fak": fak, "children": children}
    return result

def fig_org_treemap(rows: list, dims: list, faculty_colors: dict, stillingsgruppe_colors: dict = None, height: int = 500) -> go.Figure:
    """
    Plotly-native treemap med samme KU-gradueret farvestil som
    fig_org_treemap_mpl - men med bevaret hover/klik-interaktivitet.
    """
    nested = _nest_org_rows(rows, dims)
    grand_total = sum(v["total"] for v in nested.values())
    if grand_total == 0:
        return None

    def _assign_colors(group_dict, parent_color=None):
        items = sorted(group_dict.items(), key=lambda kv: -kv[1]["total"])
        if parent_color is None:
            if dims[0] == "Stil" and stillingsgruppe_colors:
                colors = {k: stillingsgruppe_colors.get(k, "#666666") for k, v in items}
            else:
                colors = {k: faculty_colors.get(v["fak"], "#666666") for k, v in items}
        else:
            shades = _hls_gradient(parent_color, len(items))
            colors = {k: shades[i] for i, (k, v) in enumerate(items)}
        for k, v in items:
            if v["children"]:
                _assign_colors(v["children"], colors[k])
        return colors

    top_colors = _assign_colors(nested)

    def _flatten(group_dict, path=(), colors=None):
        colors = colors or top_colors
        for key, v in group_dict.items():
            sub_path = path + (key,)
            yield sub_path, v["total"], colors[key]
            if v["children"]:
                child_colors = _assign_colors(v["children"], colors[key])
                yield from _flatten(v["children"], sub_path, child_colors)

    ids, labels, parents, values, colors, hovertexts = [], [], [], [], [], []
    for path, total, color in _flatten(nested):
        ids.append(" | ".join(path))
        #labels.append(path[-1])
        labels.append(_wrap_label(path[-1]))
        parents.append(" | ".join(path[:-1]) if len(path) > 1 else "")
        values.append(total)
        colors.append(color)

        pct = total / grand_total * 100
        lines = []
        for i, (dim_col, val) in enumerate(zip(dims, path)):
            label = _ORG_DIM_LABELS.get(dim_col, dim_col)
            lines.append(f"<b>{label}: {val}</b>" if i == len(path) - 1 else f"{label}: {val}")
        lines.append(f"{total:,} publikationer ({pct:.1f}%)")
        hovertexts.append("<br>".join(lines))

    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, values=values,
        marker=dict(colors=colors, line=dict(width=1, color="white"), pad=dict(t=0, b=0, l=0, r=0)),
        branchvalues="total",
        tiling=dict(packing="squarify"),
        pathbar=dict(visible=False),
        texttemplate="%{label}<br>%{value:,} (%{percentRoot})",
        textfont=dict(size=15, color="white"),
        hovertext=hovertexts,
        hovertemplate="%{hovertext}<extra></extra>",
    ))
    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=height)
    return fig

_COUNTRY_ISO3_OVERRIDES = {
    "Hong Kong": "HKG", "Taiwan": "TWN", "South Korea": "KOR",
    "Korea, Republic of": "KOR", "Vietnam": "VNM", "Russia": "RUS",
    "Iran": "IRN", "North Macedonia": "MKD", "Czech Republic": "CZE",
    "Ivory Coast": "CIV", "Bolivia": "BOL", "Tanzania": "TZA",
    "Moldova": "MDA", "Syria": "SYR", "Laos": "LAO", "Brunei": "BRN",
    "Venezuela": "VEN", "Palestine": "PSE",
    "Congo, The Democratic Republic of the": "COD", "DR Congo": "COD",
    "Turkey": "TUR",
    "Cape Verde": "CPV",
    "Swaziland": "SWZ",
}

_iso3_cache = {}
try:
    _da_country_translator = _gettext.translation(
        "iso3166-1", pycountry.LOCALES_DIR, languages=["da"]
    )
except FileNotFoundError:
    _da_country_translator = None

def _country_name_da(iso3: str) -> str:
    """Dansk navn for et ISO-3-landekode, via pycountrys indbyggede
    gettext-oversættelser. Falder tilbage til engelsk navn, hvis ingen
    dansk oversættelse findes i kataloget."""
    country = pycountry.countries.get(alpha_3=iso3)
    if country is None:
        return iso3
    if _da_country_translator is not None:
        return _da_country_translator.gettext(country.name)
    return country.name

def land_label_da(land: str) -> str:
    """
    Oversætter et landenavn (som skrevet i CURIS' Land-felt) til dansk - til
    brug i søjlediagrammer/eksport, samme underliggende opslag som kortets
    hover. Sentinel-værdier ('Ukendt', 'Andet') og navne, der ikke kan slås
    op, returneres uændret.
    """
    if land in ("Ukendt", "Andet"):
        return land
    iso3 = _country_to_iso3(land)
    if iso3 is None:
        return land
    return _country_name_da(iso3)

def _country_to_iso3(name: str) -> str | None:
    """Oversætter et landenavn (som skrevet i CURIS' Land-felt) til ISO-3.
    Cacher opslag, da pycountry.search_fuzzy er relativt langsom."""
    if name in _iso3_cache:
        return _iso3_cache[name]
    iso3 = _COUNTRY_ISO3_OVERRIDES.get(name)
    if iso3 is None:
        try:
            iso3 = pycountry.countries.search_fuzzy(name)[0].alpha_3
        except LookupError:
            iso3 = None
    _iso3_cache[name] = iso3
    return iso3


def _interpolate_colors(color_start: str, color_end: str, n: int) -> list:
    """n farver interpoleret jævnt (i RGB) mellem color_start og color_end."""
    r1, g1, b1 = mcolors.to_rgb(color_start)
    r2, g2, b2 = mcolors.to_rgb(color_end)
    colors = []
    for i in range(n):
        t = i / (n - 1) if n > 1 else 0
        r = r1 + t * (r2 - r1)
        g = g1 + t * (g2 - g1)
        b = b1 + t * (b2 - b1)
        colors.append(mcolors.to_hex((r, g, b)))
    return colors

def fig_country_choropleth(data: dict, title: str = "", bins: list = None) -> tuple:
    """
    data: {landenavn: antal publikationer}
    bins: grænseværdier for diskrete farveintervaller, fx [10, 50, 200, 1000,
    5000, 10000] - alt over sidste grænse får samme (mørkeste) farve. Antal
    intervaller = len(bins) + 1.
    Returnerer (figure, unmatched).
    """

    iso3_values, unmatched = {}, []
    unknown_count = 0
    for land, n in data.items():
        if land in ("Unknown", "Ukendt"):
            unknown_count += n
            continue
        iso3 = _country_to_iso3(land)
        if iso3:
            iso3_values[iso3] = iso3_values.get(iso3, 0) + n
        else:
            unmatched.append(land)

    locations = list(iso3_values.keys())
    values = list(iso3_values.values())

    if bins is None:
        #bins = [10, 50, 200, 1000, 5000, 10000]
        bins = [10, 50, 100, 200, 500, 1000, 2000, 3000]

    locations = list(iso3_values.keys())
    values = list(iso3_values.values())
    n_bins = len(bins) + 1

    def bin_index(v):
        for i, edge in enumerate(bins):
            if v <= edge:
                return i
        return len(bins)

    bin_indices = [bin_index(v) for v in values]

    step_colors = _interpolate_colors("#bac7d9", "#901a1e", n_bins)
    colorscale = []
    for i, color in enumerate(step_colors):
        colorscale.append([i / n_bins, color])
        colorscale.append([(i + 1) / n_bins, color])

    edges = [0] + bins
    labels = [
        f"{edges[i]:,}-{edges[i+1]:,}" if i < len(bins) else f"{bins[-1]:,}+"
        for i in range(n_bins)
    ]
    tickvals = [i + 0.5 for i in range(n_bins)]

    fig = go.Figure(go.Choropleth(
        locations=locations,
        locationmode="ISO-3",
        z=bin_indices,
        zmin=0, zmax=n_bins,
        customdata=list(zip(values, [_country_name_da(loc) for loc in locations])),
        colorscale=colorscale,
        marker_line_color="white",
        marker_line_width=0.5,
        colorbar=dict(title="Antal publikationer", tickvals=tickvals, ticktext=labels),
        hovertemplate="<b>%{customdata[1]}</b><br>%{customdata[0]:,} publikationer<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        geo=dict(
            showframe=False,
            showcoastlines=False,
            projection_type="natural earth",
            showland=True,
            landcolor="#e1dfdf",
        ),
        margin=dict(t=50, b=10, l=10, r=10),
        height=500,
    )
    return fig, unmatched, unknown_count

def fig_year_trend(
    data: dict, order: list, colors: dict = None, labels: dict = None,
    title: str = "", yaxis_title: str = "Antal", mode: str = "antal",
    pct_denominators: dict = None,   # NY: eksplicit nævner pr. år
) -> go.Figure:

    years = sorted(data.keys())

    if order is None:
        totals = {}
        for y in data.values():
            for k, v in y.items():
                totals[k] = totals.get(k, 0) + v
        order = sorted(totals, key=lambda k: -totals[k])
    
    if colors is None:
        palette = ku_color_sequence(len(order))
        colors = {k: palette[i] for i, k in enumerate(order)}
    
    if labels is None:
        labels = {k: str(k) if k else "Ikke registreret" for k in order}
    
    fig = go.Figure()
    for key in order:
        y_vals, hover_vals = [], []
        for year in years: 
            cats = data.get(year, {})
            n = cats.get(key, 0)
            if mode == "pct":
                total = (pct_denominators.get(year) if pct_denominators else None) or sum(cats.values()) or 1
                y_vals.append(round(100 * n / total, 1))
            else:
                y_vals.append(n)
            hover_vals.append(n)
        
        fig.add_trace(go.Scatter(
            x=years,
            y=y_vals,
            mode="lines+markers",
            name=labels.get(key, str(key)),
            line=dict(color=colors.get(key, "#cccccc"), width=2.5),
            marker=dict(size=6),
            customdata=hover_vals,
            hovertemplate=(
                f"<b>{labels.get(key, key)}</b><br>%{{x}}<br>"
                + ("%{y}%<br>%{customdata:,} publikationer" if mode == "pct" else "%{y:,} publikationer")
                + "<extra></extra>"
            ),
        ))

    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        xaxis=dict(title="År", dtick=1),
        yaxis=dict(
            title="Andel (%)" if mode == "pct" else yaxis_title,
            range=[0,100] if mode == "pct" else None,
        ),
        plot_bgcolor="white",
        height=420,
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02, traceorder="normal"),
        margin=dict(t=50, b=60, l=10, r=220)
    )
    return fig

def domain_shaded_colors(order: list, dim_domain_map: dict, totals: dict) -> dict:
    by_domain = {}

    for k in order:
        dom = dim_domain_map.get(k, "Ukendt")
        by_domain.setdefault(dom, []).append(k)
    
    colors = {}
    for dom, keys in by_domain.items():
        keys_sorted = sorted(keys, key=lambda k: -totals.get(k, 0))
        base = _DOMAIN_COLORS.get(dom, "#666666")
        shades = _hls_gradient(base, len(keys_sorted))
        for i, k in enumerate(keys_sorted):
            colors[k] = shades[i]
    return colors



