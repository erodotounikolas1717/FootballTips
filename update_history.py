import json, os, time, urllib.request, urllib.error
from pathlib import Path

BASE='https://sports.bzzoiro.com/api/v2'
KEY=os.getenv('BSD_API_KEY','')
PATH=Path('docs/history.json')

def get(url):
    req=urllib.request.Request(url,headers={'Authorization':f'Token {KEY}','User-Agent':'FootballTips/1.0'})
    try:
        with urllib.request.urlopen(req,timeout=25) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print('History API error:',e); return None

def result_for(market,hs,aws):
    total=hs+aws
    if market=='OVER 2.5': return total>=3
    if market=='OVER 3.5': return total>=4
    if market=='GG': return hs>=1 and aws>=1
    if market in ('OVER 2.5 + GG', 'Over 2.5 + GG'):
        return total>=3 and hs>=1 and aws>=1
    if market in ('OVER 3.5 + GG', 'Over 3.5 + GG'):
        return total>=4 and hs>=1 and aws>=1
    return None

if not KEY: raise SystemExit('BSD_API_KEY missing')
if not PATH.exists(): raise SystemExit(0)
history=json.loads(PATH.read_text(encoding='utf-8'))
changed=False
for item in history:
    if item.get('status')!='PENDING': continue
    event_id=item.get('event_id')
    if not event_id: continue
    data=get(f'{BASE}/events/{event_id}/')
    if not isinstance(data,dict): continue
    status=str(data.get('status','')).lower()
    if status!='finished': continue
    try: hs=float(data.get('home_score')); aws=float(data.get('away_score'))
    except (TypeError,ValueError): continue
    win=result_for(item.get('market'),hs,aws)
    if win is None: continue
    item['status']='WIN' if win else 'LOSS'
    item['home_score']=hs
    item['away_score']=aws
    changed=True
if changed:
    PATH.write_text(json.dumps(history,ensure_ascii=False,indent=2),encoding='utf-8')
    print('History updated')
else: print('No settled picks to update')
