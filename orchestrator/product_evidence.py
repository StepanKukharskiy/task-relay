"""Materialize purchasing evidence from exact journal spans, never authored quotes.

This checks identity and literal support, not visual suitability or live stock.
Independent review must still establish the selected span's semantic meaning.
"""
import hashlib
import copy
import json
import re

FIELDS={'name_variant','price','dimensions','order_terms','us_context'}


def displayed_prices(text):
    """Whole literal dollar-number tokens with exact offsets; never prefix parses.

    Whitespace may separate punctuation, as in separately rendered cents. It
    cannot join digits, invent a decimal point or resolve an ambiguous locale.
    These are observed numbers, not assertions of currency, variant or stock.
    """
    result=[]
    integer_pattern=re.compile(r'[0-9]+')
    separator_pattern=re.compile(r'\s*([.,])\s*([0-9]+)')
    range_pattern=re.compile(r'\s*[-–—]\s*\$?\s*[0-9]')
    exponent_pattern=re.compile(r'[eE][+-]?[0-9]')
    adjacent_pattern=re.compile(r'\s+[0-9]')
    for symbol in re.finditer(r'\$\s*',text):
        integer=integer_pattern.match(text,symbol.end())
        if integer is None:continue
        value=integer.group();pos=integer.end();decimal=False;valid=True
        while True:
            separator=separator_pattern.match(text,pos)
            if separator is None:break
            mark,digits=separator.groups()
            if decimal or (mark==',' and (len(digits)!=3 or len(value)>3 and ',' not in value)) or (mark=='.' and len(digits)>2):
                valid=False;break
            value+=mark+digits;pos=separator.end();decimal=mark=='.'
        if range_pattern.match(text,pos) or exponent_pattern.match(text,pos):valid=False
        if (not decimal or len(value.rsplit('.',1)[1])<2) and adjacent_pattern.match(text,pos):valid=False
        if pos-symbol.start()>4000:valid=False
        if valid:result.append(dict(start=symbol.start(),end=pos,text=text[symbol.start():pos],amount=value.replace(',','')))
    return sorted(result+named_currency_prices(text),key=lambda p:p['start'])

def named_currency_prices(text):
    """Explicit unambiguous symbols; never convert currencies or infer dollars.

    EUR supports decimal comma or point and grouped thousands. GBP uses decimal
    point. Exact whole tokens are retained; ambiguous/range/prefix spans fail.
    """
    result=[]
    pattern=re.compile(r'([€£])\s*([0-9]+(?:\s*[.,]\s*[0-9]+)*)')
    for match in pattern.finditer(text):
        symbol,number=match.groups();number=re.sub(r'\s+','',number)
        tail=text[match.end():]
        if re.match(r'\s*[-–—]\s*[€£$]?\s*[0-9]|[eE][+-]?[0-9]|\s+[0-9]',tail):continue
        parts=re.split(r'([.,])',number);decimal=None
        if len(parts)>1 and len(parts[-1]) in (1,2):
            decimal=parts[-2]
            if symbol=='£' and decimal!= '.':continue
            fraction=parts[-1];whole=parts[:-2]
        else:fraction=None;whole=parts
        if len(whole)>1:
            marks=whole[1::2]
            if len(set(marks))!=1 or marks[0]==decimal or not 1<=len(whole[0])<=3 or any(len(x)!=3 for x in whole[2::2]):continue
        if fraction is None and len(parts)>1 and symbol=='£' and parts[1]!=',':continue
        amount=''.join(whole[::2])+('.'+fraction if fraction is not None else '')
        if match.end()-match.start()>4000:continue
        result.append(dict(start=match.start(),end=match.end(),text=match.group(),amount=amount,currency={'€':'EUR','£':'GBP'}[symbol]))
    return result


def source_pack_journal(pack,*,discovery=False):
    """Adapt saved fetched page versions without using search/model summaries."""
    actions=[]
    for entry_index,entry in enumerate(pack['entries']):
        for page_index,page in enumerate(entry.get('pages',[])):
            ident=f'page-{entry_index}-{page_index}'
            actions.append(dict(id=ident,result=dict(observation=ident,url=page['url'],text=page['text'],
                **{k:copy.deepcopy(page[k]) for k in ('images','products','retrieved_at') if k in page})))
    if discovery:
        from .discovery_evidence import observations
        actions.extend(observations(pack))
    return dict(actions=actions,source_pack_sha256=hashlib.sha256(json.dumps(pack,sort_keys=True,ensure_ascii=False).encode()).hexdigest())

def capture(journal,selection):
    if set(selection)!={'field','observation','start','end'} or selection['field'] not in FIELDS:
        raise ValueError('Select a field and exact observation span; authored values/IDs/quotes are forbidden.')
    matches=[a for a in journal['actions'] if a['result'].get('observation')==selection['observation']]
    if len(matches)!=1:raise ValueError('Observation must resolve to exactly one original action.')
    action=matches[0];page=action['result'];text=page.get('text','')
    start,end=selection['start'],selection['end']
    if type(start) is not int or type(end) is not int or not 0<=start<end<=len(text) or end-start>4000:
        raise ValueError('Evidence span is outside the original page or too large.')
    quote=text[start:end]
    result=dict(field=selection['field'],action_id=action['id'],observation_id=page['observation'],
                url=page['url'],start=start,end=end,excerpt=quote,
                page_text_sha256=hashlib.sha256(text.encode()).hexdigest())
    if page.get('discovery'):
        if selection['field']!='name_variant':raise ValueError('Discovery titles cannot establish buying facts')
        result['discovery']=copy.deepcopy(page['discovery'])
    if selection['field']=='price':
        # Parse the complete original observation before applying selection
        # bounds, so selecting only '$69' out of '$69.99' cannot drop cents.
        prices=[p for p in displayed_prices(text) if start<=p['start'] and p['end']<=end]
        amounts=[p['amount'] for p in prices]
        if any(symbol in quote for symbol in '$€£') and (sum(quote.count(symbol) for symbol in '$€£')!=1 or len(prices)!=1):
            raise ValueError('Select one complete unambiguous displayed price; do not truncate digits, separators or ranges.')
        structured=False
        if '"price"' in quote or '"priceCurrency"' in quote:
            # Literal JSON-LD offer spans may display a number and currency
            # separately. Retain both; a range/list/Was price is still distinct.
            currencies=re.findall(r'"priceCurrency"\s*:\s*"([A-Z]{3})"',quote)
            values=re.findall(r'"price"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?(?=\s*[,}])',quote)
            if len(values)!=1 or len(currencies)!=1:raise ValueError('Select one complete literal offer number and currency.')
            from decimal import Decimal
            if amounts and (len(amounts)!=1 or Decimal(amounts[0])!=Decimal(values[0])):
                raise ValueError('Displayed and structured price numbers disagree; select unambiguous evidence.')
            amounts=values;structured=True
        if len(amounts)!=1:raise ValueError('Select exactly one displayed price; previous/current price choice requires review.')
        result['amount']=amounts[0].replace(',','')
        if prices and prices[0].get('currency'):
            if structured and currencies[0]!=prices[0]['currency']:raise ValueError('Displayed and structured currencies disagree.')
            result['currency']=prices[0]['currency']
        if structured:result.update(currency=currencies[0],price_basis='literal-jsonld-offer; selected variant/currentness require review')
    else:result['value']=quote
    return result

def verify(journal,record):
    expected=capture(journal,dict(field=record['field'],observation=record['observation_id'],start=record['start'],end=record['end']))
    if record!=expected:raise ValueError('Captured evidence changed or contradicts its original page span.')
    return expected

def materialize(journal,selections):
    return dict(version=1,kind='captured_product_fields',
                journal_sha256=hashlib.sha256(json.dumps(journal,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                fields=[capture(journal,s) for s in selections],
                limitations=['Captured spans establish literal source support, not semantic correctness, visual match or stock.',
                             'Order controls do not establish stock/delivery. Currency/country and current versus previous price require review.'])

if __name__=='__main__':
    import sys
    source=json.load(open(sys.argv[1]));selections=json.load(open(sys.argv[2]))
    journal=source if 'actions' in source else source_pack_journal(source)
    output=materialize(journal,selections)
    for record in output['fields']:verify(journal,record)
    with open(sys.argv[3],'w') as target:json.dump(output,target,indent=2,ensure_ascii=False)
