"""Conservative code-owned table typography and pagination; never drop cells."""
import math
import re
import unicodedata

MIN_FONT=14
MAX_FONT=16
WIDTH=12.1
HEIGHT=4.8


def paginate_text(page):
    """Reject overflowing fixed boxes before commit; never split labels or URLs."""
    for e in page['elements']:
        if e['type']!='text':continue
        capacity=max(1,int((e['h']-.06)*72/(e['font_size']*1.25)))
        needed=lines(e['text'],e['w'],e['font_size'],.55)
        if needed>capacity:
            raise ValueError(f"Text slot {e['name']} needs {needed} estimated lines, but its readable box holds {capacity}. Shorten this field or supply additional explicit content groups; keep a claim, its qualifications and source link together. No content was committed or truncated.")
    yield page


def lines(text,width,font,advance=.65):
    # Conservative advance budget, including wide Unicode and explicit newlines.
    # This is a layout estimate, not a promise about every substituted host font.
    capacity=max(1,(width-.12)*72/(font*advance))
    total=0
    for line in text.split('\n'):
        count=1;used=0
        for token in re.findall(r'\S+|\s+',line):
            units=sum(2 if unicodedata.east_asian_width(c) in ('W','F') or c in 'MW@' else 1 for c in token)
            if used and used+units>capacity:
                count+=1;used=0
                if token.isspace():continue
            while units>capacity:
                count+=1;units-=capacity
            used+=units
        total+=count
    return total



def row_height(row,font):
    return max(lines(v,WIDTH/len(row),font) for v in row)*font*1.3/72+.10


def pages(rows):
    if not isinstance(rows,list) or not rows or not isinstance(rows[0],list) or not 1<=len(rows[0])<=10:
        raise ValueError('Table requires 1–10 columns')
    cols=len(rows[0])
    if len(rows)>100 or any(not isinstance(r,list) or len(r)!=cols or any(not isinstance(v,str) or len(v)>4000 for v in r) for r in rows):
        raise ValueError('Table requires bounded rectangular text rows')
    # Prefer 16pt, use 14pt when needed, then paginate rather than shrink further.
    font=MAX_FONT if sum(row_height(r,MAX_FONT) for r in rows)<=HEIGHT else MIN_FONT
    header=rows[0];header_h=row_height(header,font)
    if header_h>=HEIGHT:raise ValueError('Table header exceeds readable slide capacity; shorten labels')
    if any(header_h+row_height(r,font)>HEIGHT for r in rows[1:]):
        # Dense columns become record detail tables. Column labels and every value
        # survive in source order; repeated record labels provide navigation.
        if cols<=2:raise ValueError('A table cell exceeds readable slide capacity; split its content into sections')
        for index,row in enumerate(rows[1:],1):
            details=[['Field','Value'],*[[label,value] for label,value in zip(header,row)]]
            for detail in pages(details):yield dict(**detail,record=index)
        return
    current=[header];heights=[header_h]
    for row in rows[1:]:
        height=row_height(row,font)
        if sum(heights)+height>HEIGHT:
            yield dict(rows=current,row_heights=heights,font_size=font)
            current=[header];heights=[header_h]
        current.append(row);heights.append(height)
    yield dict(rows=current,row_heights=heights,font_size=font)


def flow_blocks(blocks,width,height,font):
    """Paginate literal text blocks at a fixed readable size, retaining all text.

    Prefer whole blocks. Oversized blocks continue at whitespace boundaries;
    callers repeat the heading and source context on every continuation page.
    Estimates are conservative; rendered review remains required.
    """
    capacity=int((height-.12)*72/(font*1.3))
    if capacity<1:raise ValueError('Text flow has no readable line capacity')
    current=[];used=0
    for block in blocks:
        if not isinstance(block,str):raise ValueError('Text flow needs literal strings')
        remaining=block
        while remaining:
            needed=lines(remaining,width,font)
            if needed<=capacity:
                if current and used+needed+1>capacity:
                    yield current;current=[];used=0
                current.append(remaining);used+=needed+(1 if len(current)>1 else 0);break
            if current:yield current;current=[];used=0
            lo,hi=1,len(remaining)
            while lo<hi:
                mid=(lo+hi+1)//2
                if lines(remaining[:mid],width,font)<=capacity:lo=mid
                else:hi=mid-1
            cut=lo
            spaces=[m.end() for m in re.finditer(r'\s+',remaining[:cut])]
            if spaces:cut=spaces[-1]
            if cut<1:raise ValueError('Text flow cannot retain one character')
            yield [remaining[:cut]];remaining=remaining[cut:]
    if current:yield current
