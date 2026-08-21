from PIL import Image
from shipwright.screenshots import API_SIZE, WEB_SIZE, Panel, compose, to_web_size


def test_compose_sizes_and_pixel_fidelity():
    cap = Image.new("RGB", (1320, 2868), (10, 200, 30))
    img = compose(cap, Panel("list", "Clipboard Manager", "Everything you copy, one tap to paste"), {"bg_top": "#5856D6", "bg_bottom": "#8E5CF6"})
    assert img.size == API_SIZE
    # the real capture is pasted, not repainted: centre pixel of the device area is the capture's colour
    assert img.getpixel((660, 1700)) == (10, 200, 30)
    assert to_web_size(img).size == WEB_SIZE
