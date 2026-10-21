"""Approved attribution layout, raster invariants and AMD foreground parity."""
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image, ImageChops

from src.map_attribution import (MapAttributionRenderer, AttributionLayoutError,
    apply_map_attribution, build_map_foreground_tile)
from src.indicators.helpers import map_style_layers, apply_map_opacity
from src.indicators.moving_map import build_static_map_marker_tile

TEXT = "Powered by Esri | Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community"


@pytest.fixture(autouse=True)
def attribution():
    MapAttributionRenderer.clear_cache()
    with patch("src.integrations.esri.esri_client.attribution", TEXT):
        yield


@pytest.mark.parametrize("size", [(240,240),(480,480),(960,960),(320,180),(640,360)])
@pytest.mark.parametrize("shape", ["square","rounded","circle","round"])
def test_full_text_inside_mask_and_below_marker(size, shape):
    overlay = MapAttributionRenderer.get_attribution_overlay("satellite", *size, shape=shape)
    bounds = overlay.getbbox()
    assert bounds and bounds[1] > size[1] * .5
    assert 0 <= bounds[0] < bounds[2] <= size[0]
    assert bounds[3] <= size[1]
    layers = map_style_layers(size,shape,16,0,"#FFFFFF")
    if layers:
        outside = ImageChops.multiply(overlay.getchannel("A"),ImageChops.invert(layers[0]))
        assert outside.getbbox() is None
    # A cache hit must not measure geometry or rasterize fonts again.
    with patch("PIL.ImageFont.truetype",side_effect=AssertionError("rerasterized")):
        assert MapAttributionRenderer.get_attribution_overlay("satellite", *size, shape=shape) is overlay


def test_approved_style_alpha_and_reference_scale():
    overlay = MapAttributionRenderer.get_attribution_overlay("satellite",240,240)
    alpha = np.asarray(overlay)[:,:,3]
    assert np.count_nonzero(alpha == 80) > 100  # approved black background alpha
    assert alpha.max() >= 230  # text remains substantially opaque
    big = MapAttributionRenderer.get_attribution_overlay("satellite",480,480)
    a,b = overlay.getbbox(),big.getbbox()
    assert abs((b[3]-b[1]) - 2*(a[3]-a[1])) <= 4


def test_cache_includes_text_font_padding_shape():
    original = MapAttributionRenderer.get_attribution_overlay("satellite",240,240)
    changed = MapAttributionRenderer.get_attribution_overlay("satellite",240,240,text=TEXT+", Test source")
    assert changed is not original
    assert MapAttributionRenderer.get_attribution_overlay("satellite",240,240,padding=5) is not original
    assert MapAttributionRenderer.get_attribution_overlay("satellite",240,240,font_size=10) is not original
    assert MapAttributionRenderer.get_attribution_overlay("satellite",240,240,shape="rounded") is not original


def test_too_small_map_fails_explicitly_instead_of_dropping_sources():
    with pytest.raises(AttributionLayoutError,match="Zwiększ"):
        MapAttributionRenderer.get_attribution_overlay("satellite",50,50)


@pytest.mark.parametrize("size", [(240,240),(480,480),(960,540)])
@pytest.mark.parametrize("shape", ["square","rounded","circle"])
def test_cpu_and_amd_foreground_are_pixel_identical(size,shape):
    cfg = {"map_shape":shape,"opacity":.7,"show_attribution":False}
    # Both adapters use the same output-space bitmap after rotation/pitch.
    cpu = apply_map_opacity(apply_map_attribution(Image.new("RGBA",size),"satellite",cfg),.7)
    tile,rect = build_map_foreground_tile(size,"satellite",cfg)
    gpu = Image.new("RGBA",size)
    gpu.paste(tile,(rect[0],rect[1]))
    assert cpu.tobytes() == gpu.tobytes()


def test_map_pixels_outside_attribution_and_marker_do_not_change():
    size=(240,240)
    rng=np.random.default_rng(20261021)
    pixels=rng.integers(0,256,(240,240,4),dtype=np.uint8); pixels[:,:,3]=255
    before=Image.fromarray(pixels)
    after=apply_map_attribution(before,"satellite",{})
    mask=np.asarray(MapAttributionRenderer.get_attribution_overlay("satellite",*size))[:,:,3]>0
    diff=np.abs(np.asarray(before).astype(int)-np.asarray(after).astype(int))
    assert diff[~mask].max()==0
    assert np.array_equal(np.asarray(before)[110:130,110:130],np.asarray(after)[110:130,110:130])


def test_original_directional_marker_pixels_are_preserved_in_gpu_tile():
    cached=MapAttributionRenderer.get_attribution_overlay("satellite",240,240)
    before=cached.tobytes()
    marker,rect=build_static_map_marker_tile(240,7,"directional")
    foreground,box=build_map_foreground_tile((240,240),"satellite",{},marker,rect)
    full=Image.new("RGBA",(240,240)); full.paste(foreground,box[:2])
    x,y,w,h=rect
    assert full.crop((x,y,x+w,y+h)).tobytes()==marker.tobytes()
    assert cached.tobytes()==before


def test_switching_provider_uses_its_own_sources():
    from src.map_providers import MapProviderRegistry
    assert "CARTO" in MapProviderRegistry.get_attribution("light_all")[0]
    assert "Vantor" in MapProviderRegistry.get_attribution("satellite")[0]
    assert "CARTO" not in MapProviderRegistry.get_attribution("satellite")[0]


@pytest.mark.parametrize("kind",["moving","static"])
@pytest.mark.parametrize("shape",["square","rounded","circle"])
@pytest.mark.parametrize("orientation",["north_up","track_up"])
def test_indicator_preview_and_final_both_apply_mandatory_attribution(kind,shape,orientation):
    from datetime import datetime,timedelta,timezone
    from src.indicators.moving_map import _render_moving_map_indicator,clear_moving_map_cache
    from src.indicators.static_map import _render_static_map_indicator
    class Renderer:
        def __init__(self,*args,**kwargs):
            pass
        def viewport_tile_coverage(self,*args):
            return 1.0
        def render(self,ts,w,h,**kwargs):
            return Image.new("RGBA",(w,h),(60,90,62,255))
        def render_track_up(self,ts,w,**kwargs):
            return self.render(ts,w,w)
    start=datetime(2026,10,21,tzinfo=timezone.utc)
    track=[(start,52.,21.),(start+timedelta(seconds=10),52.01,21.01)]
    cfg={"x":50,"y":50,"size":12.5,"zoom":16,"map_style":"satellite",
         "map_shape":shape,"map_orientation":orientation,"show_attribution":False}
    function=_render_moving_map_indicator if kind=="moving" else _render_static_map_indicator
    def render(async_map,heading,position):
        return function(1920,1080,{},"","track_map",None,"","Mapa",cfg,1080,1,12,None,
                        0,100,0,2,240,1,gps_track=track,async_map=async_map,
                        current_position=position,map_heading=heading)[0]
    with patch("src.moving_map.MovingMapRenderer",Renderer), \
         patch("src.indicators.static_map._tile_cached",return_value=True), \
         patch("src.map_renderer.render_map_overlay",side_effect=lambda track,ci,w,h,**kw: Image.new("RGBA",(w,h),(60,90,62,255))):
        clear_moving_map_cache()
        for heading,position in ((0,0),(90,.5),(270,1)):
            preview=render(True,heading,position)
            final=render(False,heading,position)
            assert preview is not None and final is not None
            assert preview.tobytes()==final.tobytes()
            # The attribution is present even when an old preset disables it.
            overlay=MapAttributionRenderer.get_attribution_overlay("satellite",240,240,shape=shape)
            x,y,right,bottom=overlay.getbbox()
            assert len(set(final.crop((x,y,right,bottom)).getdata()))>4
        clear_moving_map_cache()
