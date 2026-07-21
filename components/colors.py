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

_KU_HUE_FAMILIES = [
    colorsys.rgb_to_hls(*mcolors.to_rgb("#122947"))[0],  # Blå
    colorsys.rgb_to_hls(*mcolors.to_rgb("#901a1E"))[0],  # Rød
    colorsys.rgb_to_hls(*mcolors.to_rgb("#39641c"))[0],  # Grøn
    colorsys.rgb_to_hls(*mcolors.to_rgb("#0a5963"))[0],  # Petroleum
    colorsys.rgb_to_hls(*mcolors.to_rgb("#ffbd38"))[0],  # Gul
]
_KU_GRAA_HUE = 0.0   # neutral - mætning tvinges altid til 0, uanset hue-værdien

_SHADE_L = [0.24, 0.34, 0.44, 0.54, 0.64, 0.74, 0.84,
            0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80,
            0.28, 0.38, 0.48, 0.58]
_SHADE_S = [0.80, 0.72, 0.64, 0.56, 0.48, 0.40, 0.32,
            0.85, 0.76, 0.68, 0.60, 0.52, 0.44, 0.36,
            0.78, 0.70, 0.62, 0.54]

def _extra_ku_shades(n: int) -> list[str]:
    """
    Genererer n ekstra farver ved at variere lyshed/mætning inden for KU's
    officielle farvetoner (samme hue som _KU_HUE_FAMILIES). Bruges kun når
    _KU_PALETTE_RAW er brugt op.
    """
    shades = []
    hues = _KU_HUE_FAMILIES + [_KU_GRAA_HUE]
    shade_idx = 0
    while len(shades) < n:
        l = _SHADE_L[shade_idx % len(_SHADE_L)]
        s = _SHADE_S[shade_idx % len(_SHADE_S)]
        for i, hue in enumerate(hues):
            use_s = 0.0 if i == len(hues) - 1 else s   # sidste hue = Grå -> altid S=0
            r, g, b = colorsys.hls_to_rgb(hue, l, use_s)
            shades.append(mcolors.to_hex((r, g, b)))
            if len(shades) >= n:
                break
        shade_idx += 1
    return shades


def ku_color_sequence(n: int, seed: int = 26) -> list[str]:
    if n <= len(_KU_PALETTE_RAW):
        return _KU_PALETTE_RAW[:n]
    return _KU_PALETTE_RAW + _extra_ku_shades(n - len(_KU_PALETTE_RAW))

def build_faculty_colors() -> dict:
    return {
        "TEO": "#3A1A5F",
        "JUR": "#7d5402",
        "HUM": "#122947",      # Blå mørk
        "SCIENCE": "#39641c",  # Grøn mørk
        "SAMF": "#0a5963",     # Petroleum mørk
        "SUND": "#7A131A",
    }

def stillingsgruppe_colors() -> dict:
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




