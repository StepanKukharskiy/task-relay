"""Local, exact-pixel crop adapter. Coordinates refer to the oriented image."""
import hashlib
import io


def crop(raw, media_type, region):
    from PIL import Image, ImageOps
    from .browser_contract import png_info, MAX_PNG_BYTES
    if len(raw)>MAX_PNG_BYTES:raise ValueError('Crop source exceeds 10 MB')
    if not isinstance(region,list) or len(region)!=4 or any(type(n) is not int or n<0 for n in region):
        raise ValueError('Crop region needs integer x, y, width, height')
    x,y,w,h=region
    if not w or not h:raise ValueError('Crop dimensions must be positive')
    with Image.open(io.BytesIO(raw)) as source:
        if source.format!={'image/png':'PNG','image/jpeg':'JPEG'}.get(media_type):
            raise ValueError('Crop source format differs from declared media type')
        if source.width*source.height>32_000_000 or getattr(source,'n_frames',1)!=1:
            raise ValueError('Crop source must be a bounded static image')
        oriented=ImageOps.exif_transpose(source)
        if x+w>oriented.width or y+h>oriented.height:raise ValueError('Crop region leaves source pixels')
        if max(w,h)>4096 or w*h>8_000_000:raise ValueError('Crop exceeds browser PNG dimensions')
        result=oriented.convert('RGBA').crop((x,y,x+w,y+h))
        out=io.BytesIO();result.save(out,format='PNG');data=out.getvalue();png_info(data)
        receipt=dict(source_sha256=hashlib.sha256(raw).hexdigest(),region=region,
                     source_dimensions=list(oriented.size),output_sha256=hashlib.sha256(data).hexdigest(),
                     coordinates='pixels after EXIF orientation',acceptance=False)
        return data,receipt
