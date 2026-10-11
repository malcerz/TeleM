from PIL import Image, ImageDraw
import numpy as np
from src.indicators.effects import apply_indicator_effects
from src.indicators.compositor import compose_overlay
from src.gui.qt.models import get_schema_for_form


def tile():
    im = Image.new("RGBA", (40,40))
    ImageDraw.Draw(im).rectangle((12,12,27,27),fill="white")
    return im


def test_disabled_effects_preserve_identity():
    im=tile()
    assert apply_indicator_effects(im,{},540) is im


def test_shadow_length_fade_and_outline_fade_are_effective():
    im=tile()
    base={"shadow_enabled":True,"shadow_distance":3,"shadow_length":15,"shadow_fade":0}
    flat=apply_indicator_effects(im,base,540)
    faded=apply_indicator_effects(im,dict(base,shadow_fade=1),540)
    assert np.asarray(flat)[:,:,3].sum()>np.asarray(faded)[:,:,3].sum()
    short=apply_indicator_effects(im,dict(base,shadow_length=0),540)
    assert short.size!=flat.size
    cfg={"outline_enabled":True,"outline_width":5,"outline_fade":0}
    hard=apply_indicator_effects(im,cfg,540)
    soft=apply_indicator_effects(im,dict(cfg,outline_fade=1),540)
    assert np.asarray(hard)[:,:,3].sum()>np.asarray(soft)[:,:,3].sum()
    # The original core is neither shrunk nor recoloured.
    pad=(hard.width-im.width)//2
    assert hard.crop((pad+12,pad+12,pad+28,pad+28)).tobytes()==im.crop((12,12,28,28)).tobytes()


def test_effect_support_unclipped_and_resolution_scaled():
    cfg={"shadow_enabled":True,"shadow_distance":5,"shadow_length":20,"shadow_angle":225,
         "outline_enabled":True,"outline_width":4}
    for scale in (1,2,4):
        im=tile().resize((40*scale,40*scale))
        result=apply_indicator_effects(im,cfg,540*scale)
        box=result.getchannel("A").getbbox()
        assert box[0]>0 and box[1]>0 and box[2]<result.width and box[3]<result.height


def test_effect_schema_and_bright_surface_preview_export_parity():
    for form in ("text","gauge","compass","bar","lean","time_display"):
        assert {"outline_width","outline_fade","shadow_length","shadow_fade"} <= {f.name for f in get_schema_for_form(form)}
    for form,key in (("text","speed_text"),("gauge","speed_visual"),("compass","compass"),("bar","dist_visual")):
        cfg={"enabled":True,"form":"gauge" if form=="compass" else form,"gauge_style":"compass" if form=="compass" else "default",
             "x":50,"y":50,"size":12,"font_size":2,"min_val":0,"max_val":100,
             "outline_enabled":True,"outline_width":2,"outline_fade":0.5,
             "shadow_enabled":True,"shadow_length":8,"shadow_fade":1}
        layout={"global":{"text_outline":3},"indicators":{key:cfg}}
        for w,h in ((960,540),(1920,1080),(3840,2160)):
            images=[]
            for _ in range(2):
                hud=compose_overlay(w,h,layout,r"C:\Windows\Fonts\arial.ttf","","",25,1000,
                    indicator_values={key:90},render_keys={key},reuse_canvas=False)
                images.append(Image.alpha_composite(Image.new("RGBA",(w,h),"white"),hud))
            assert images[0].tobytes()==images[1].tobytes()
            arr=np.asarray(images[0])
            assert (arr[:,:,:3].min(axis=2)<50).any()


def test_property_editor_exposes_both_compass_modes_and_effects():
    from PySide6.QtWidgets import QApplication
    from src.gui.qt.widgets.property_editor import PropertyEditor
    from src.gui.qt.models import compass_indicator_fields
    app=QApplication.instance() or QApplication([])
    editor=PropertyEditor()
    editor.on_properties_ready("compass",compass_indicator_fields(),{"compass_rotation_mode":"rose","shadow_length":12,"outline_fade":0.5})
    app.processEvents()
    fields=editor._field_widgets
    combo=fields["compass_rotation_mode"]
    assert combo.count()==2
    assert combo.currentData()=="rose"
    assert fields["shadow_length"].value()==12
    assert fields["outline_fade"].value()==0.5
    combo.setCurrentIndex(0)
    assert combo.currentData()=="needle"
    editor.close()
