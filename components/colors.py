from matplotlib import colors as mcolors
import colorsys

_KU_PALETTE_RAW = [
    # Mørke - høj kontrast, bruges først
    "#122947",  # Blå mørk
    "#901a1E",  # Rød mørk
    "#39641c",  # Grøn mørk
    "#0a5963",  # Petroleum mørk
    "#3d3d3d",  # Grå mørk
    "#7d5402",  # Brun mørk (JUR)
    # Mellem - god læsbarhed
    "#ffbd38",  # Gul (adskiller)
    "#4b8325",  # Grøn mellem
    "#c73028",  # Rød mellem
    "#197f8e",  # Petroleum mellem
    "#425570",  # Blå mellem
    "#666666",  # Grå mellem
    # Lyse - bruges sidst, kun ved mange kategorier
    "#bac7d9",  # Blå lys
    "#dB3B0A",  # Rød-orange lys
    "#becaa8",  # Grøn lys
    "#b7d7de",  # Petroleum lys
    "#e1dfdf",  # Grå lys
]

def ku_color_sequence(n: int, seed: int = 26) -> list[str]:
    if n <= len(_KU_PALETTE_RAW):
        return _KU_PALETTE_RAW[:n]
    plotly_defaults = [
        "#3A1A5F", "#7d5402", "#c45c5f", "#5C1012",
        "#6B84A0", "#fefaf2", "#7A131A", "#aaaaaa",
        "#ffbd38", "#becaa8",
    ]
    extras = plotly_defaults * ((n - len(_KU_PALETTE_RAW)) // len(plotly_defaults) + 1)

    return _KU_PALETTE_RAW + extras[:n - len(_KU_PALETTE_RAW)]

def build_faculty_colors(ku_farver: dict) -> dict:
    return {
        "TEO": "#3A1A5F",
        "JUR": "#7d5402",
        "HUM": ku_farver["Blaa"]["Moerk"],
        "SCIENCE": ku_farver["Groen"]["Moerk"],
        "SAMF": ku_farver["Petroleum"]["Moerk"],
        "SUND": "#7A131A",
    }

def stillingsgruppe_colors(ku_farver: dict) -> dict:
    return {
        "Særlig stilling": "#D4D4D4",
        "Øvrige VIP (DVIP)": "#BAC7D9",
        "Ph.d.": "#6B84A0",
        "Stillinger u. adjunktniveau": "#425570",
        "Postdoc": "#AAAAAA",
        "Adjunkt": "#C45C5F",
        "Lektor": "#901A1E",
        "Professor": "#5C1012",
    }

def adjust_color(hex_color: str, lightness_factor: float = 1.0, saturation_factor: float = 1.0) -> str:
    r, g, b = mcolors.to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(0.0, min(1.0, l * lightness_factor))
    s = max(0.0, min(1.0, s * saturation_factor))
    r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
    return mcolors.to_hex((r2, g2, b2))
 
def add_alpha(hex_color: str, alpha: float) -> str:
    r, g, b = mcolors.to_rgb(hex_color)
    return f"rgba({int(r*255)}, {int(g*255)}, {int(b*255)}, {alpha})"




