#!/usr/bin/env python3
"""Offline Workers AI authoring. Candidates never enable production languages."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TOKENS = re.compile(r'\{[A-Za-z_][A-Za-z0-9_]*\}')
MODEL = '@cf/zai-org/glm-4.7-flash'


def validate(source, candidate):
    if not isinstance(candidate, dict) or set(source) != set(candidate):
        raise ValueError('translation_key_mismatch')
    for key, original in source.items():
        value = candidate[key]
        if not isinstance(value, str) or not value.strip() or '[object Object]' in value or '\ufffd' in value:
            raise ValueError(f'translation_invalid_value:{key}')
        if sorted(TOKENS.findall(original)) != sorted(TOKENS.findall(value)):
            raise ValueError(f'translation_placeholder_mismatch:{key}')
        value.encode('utf-8', errors='strict')
    if all(candidate[k] == v for k,v in source.items()):
        raise ValueError('translation_no_progress')
    return candidate


def translate(locale, source):
    account = os.environ.get('CLOUDFLARE_ACCOUNT_ID', '')
    token = os.environ.get('CLOUDFLARE_API_TOKEN', '')
    if not re.fullmatch(r'[a-fA-F0-9]{32}', account) or not token:
        raise RuntimeError('Required: CLOUDFLARE_ACCOUNT_ID (32 hex digits) and CLOUDFLARE_API_TOKEN (Workers AI Read permission)')
    endpoint = f'https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{MODEL}'
    prompt = (f'Translate these English enterprise agriculture UI strings into the exact BCP-47 locale {locale}. '
              'For pt-BR use Brazilian Portuguese. Return only a JSON object with the exact input keys. '
              'Preserve placeholder tokens including braces, multiplicity, markup, URLs, AGRO-AI, product names, '
              'technical identifiers, units and numeric values. Translate all human-facing copy naturally; no explanations.')
    payload = {'messages':[{'role':'system','content':prompt},{'role':'user','content':json.dumps(source,ensure_ascii=False)}],
               'temperature':0,'max_completion_tokens':8192}
    request = urllib.request.Request(endpoint,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':f'Bearer {token}'})
    try:
        with urllib.request.urlopen(request,timeout=120) as response: body=json.load(response)
    except urllib.error.HTTPError as error:
        # Only emit public error codes, never request headers or provider bodies.
        raise RuntimeError(f'workers_ai_http_{error.code}; verify token permissions, model access and quota') from None
    if body.get('success') is False:
        codes=[str(e.get('code','unknown')) for e in body.get('errors',[]) if isinstance(e,dict)]
        raise RuntimeError('workers_ai_failed_codes:'+','.join(codes))
    raw=body.get('result',{}).get('response','')
    raw=re.sub(r'^```(?:json)?\s*|\s*```$', '',raw.strip())
    return validate(source,json.loads(raw))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--locales',required=True)
    parser.add_argument('--preflight',action='store_true')
    args=parser.parse_args()
    locales=args.locales.split(',')
    if any(not re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*',x) for x in locales):
        raise ValueError('Invalid locale identifier')
    if args.preflight:
        result=translate(locales[0],{'createAccount':'Create account','fullName':'Full name'})
        print(json.dumps({'status':'ok','locale':locales[0],'catalog':result},ensure_ascii=False)); return
    source=json.loads((ROOT/'shared/localization/source.json').read_text())
    outdir=ROOT/'shared/localization/candidates'; outdir.mkdir(exist_ok=True)
    for locale in locales:
        dest=outdir/f'{locale}.json'; catalog={}
        if dest.exists():
            old=json.loads(dest.read_text())
            catalog={k:v for k,v in old['catalog'].items() if old.get('source',{}).get(k)==source['catalog'].get(k)}
        by_value={}
        for key,value in source['catalog'].items():
            if key not in catalog: by_value.setdefault(value,[]).append(key)
        entries=[(keys[0],value) for value,keys in by_value.items()]
        for i in range(0,len(entries),24):
            chunk=dict(entries[i:i+24]); result=translate(locale,chunk)
            for key,value in result.items():
                for alias in by_value[source['catalog'][key]]: catalog[alias]=value
            envelope={'schemaVersion':1,'locale':locale,'direction':'rtl' if locale in ('ar','fa','ur') else 'ltr',
                      'sourceFingerprint':source['sourceFingerprint'],'status':'unreviewed-candidate',
                      'provider':'cloudflare_workers_ai_build_time','model':MODEL,'source':source['catalog'],
                      'catalog':dict(sorted(catalog.items()))}
            dest.write_text(json.dumps(envelope,ensure_ascii=False,indent=2)+'\n')
            print(locale,'candidate',len(catalog),'/',len(source['catalog']),flush=True)
if __name__=='__main__': main()
