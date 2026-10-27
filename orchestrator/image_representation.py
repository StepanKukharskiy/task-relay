"""Bounded display representations retaining separately hashed source originals."""
import io


def inspection_preview(raw, name):
    """Bounded model pixels; original file bytes and identity stay unchanged."""
    from .browser_contract import png_info, MAX_PNG_BYTES
    kind='JPEG' if name.lower().endswith(('.jpg','.jpeg')) else 'PNG'
    if not isinstance(raw,bytes) or len(raw)>MAX_PNG_BYTES:
        raise ValueError('Image exceeds inspection allowance')
    if kind=='PNG':
        try:
            info=png_info(raw)
            return raw,dict(source_dimensions=[info['width'],info['height']],transformation='identity')
        except ValueError as exc:
            # Corrupt/truncated PNGs are not repaired by a decoder. Only the
            # display dimension limit is eligible for a derived preview.
            if str(exc)!='Screenshot dimensions exceed bounds':raise
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as source:
        maximum=16_000_000 if kind=='JPEG' else 20_000_000
        if source.format!=kind or source.width*source.height>maximum or getattr(source,'n_frames',1)!=1:
            raise ValueError('Unsupported or oversized static inspection source')
        dimensions=list(source.size);source.verify()
    with Image.open(io.BytesIO(raw)) as source:
        picture=source.convert('RGB' if kind=='JPEG' else 'RGBA')
    resized=False
    if max(picture.size)>4096 or picture.width*picture.height>8_000_000:
        picture.thumbnail((2048,2048),Image.Resampling.LANCZOS);resized=True
    while True:
        output=io.BytesIO();picture.save(output,format='PNG');data=output.getvalue()
        if len(data)<=MAX_PNG_BYTES:break
        # Lossless JPEG conversion can exceed the unchanged output allowance.
        # Reduce only the display representation, never the stored source.
        size=tuple(max(1,int(n*.75)) for n in picture.size)
        if size==picture.size:raise ValueError('Inspection preview cannot fit its byte allowance')
        picture=picture.resize(size,Image.Resampling.LANCZOS);resized=True
    png_info(data)
    return data,dict(source_dimensions=dimensions,
                     transformation='bounded-inspection-preview-v1' if resized else 'jpeg-to-png')


def png_preview(raw,mime,maximum):
    from PIL import Image
    kind={'image/webp':'webp','image/avif':'avif'}[mime]
    with Image.open(io.BytesIO(raw)) as source:
        if getattr(source,'n_frames',1)!=1:raise ValueError('Animated '+('WebP' if kind=='webp' else 'AVIF')+' is not a static product photo.')
        source.load();picture=source.copy()
        metadata={k:source.info[k] for k in ('icc_profile','exif') if source.info.get(k)}
        def encode():
            out=io.BytesIO();picture.save(out,format='PNG',**metadata);return out.getvalue()
        result=encode()
        if len(result)<=maximum:return result,'lossless-'+kind+'-to-png'
        # The original remains untouched in the bundle. This representation is
        # explicitly a downsampled preview, not a claim of pixel equivalence.
        if max(picture.size)>2048 and min(picture.size)*2048/max(picture.size)>=100:picture.thumbnail((2048,2048),Image.Resampling.LANCZOS)
        while True:
            result=encode()
            if len(result)<=maximum:return result,'bounded-preview-v1-'+kind+'-to-png'
            if min(picture.size)<=100:raise ValueError('Image representation cannot fit its frozen byte allowance at the minimum source dimensions')
            scale=max(.75,100/min(picture.size))
            picture=picture.resize(tuple(max(100,int(n*scale)) for n in picture.size),Image.Resampling.LANCZOS)


def verify_preview(source,data,mime,transformation,maximum):
    from PIL import Image
    expected,kind=png_preview(source,mime,maximum)
    if kind!=transformation:raise ValueError('Source-original representation policy differs')
    with Image.open(io.BytesIO(expected)) as before,Image.open(io.BytesIO(data)) as after:
        if before.size!=after.size or before.convert('RGBA').tobytes()!=after.convert('RGBA').tobytes():
            raise ValueError('Converted photo pixels differ from the declared source representation')
