"""Monitor all FPL players and discover news evidence (standard library only).

Github Actions writes a compact snapshot and a *candidate* news inbox.
News headlines are never promoted into availability_reports.json automatically;
this would be unsafe without dependable article-level extraction/verification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import re
import urllib.request
import urllib.parse
from xml.etree import ElementTree as ET

BASE = 'https://fantasy.premierleague.com/api/bootstrap-static/'
DEFAULT_FEEDS = ['https://feeds.theguardian.com/theguardian/football/premierleague/rss']
HEADERS = {'User-Agent': 'AJKBolaWaweiAI/7.21 (non-commercial FPL monitoring; hourly cache)'}


def fetch(url: str, limit: int = 5_000_000) -> bytes:
    if not url.startswith('https://'):
        raise ValueError('Only HTTPS feeds supported')
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=22) as response:
        data = response.read(limit+1)
        if len(data) > limit:
            raise ValueError('Response too large')
        return data


def player_snapshot(payload: dict, as_of: str) -> dict:
    rows = {}
    for p in payload.get('elements', []):
        pid = str(int(p['id']))
        rows[pid] = {k:p.get(k) for k in ('id','team','first_name','second_name','web_name',
                   'status','chance_of_playing_next_round','chance_of_playing_this_round',
                   'news','news_added','minutes','starts','form','expected_goals',
                   'expected_assists','now_cost')}
    return {'schema_version':1, 'updated_at':as_of, 'players':rows}


def compare(old: dict, new: dict) -> list[dict]:
    changes = []
    for pid, row in new.get('players',{}).items():
        prior = old.get('players',{}).get(pid)
        if not prior:
            continue
        fields = ('status','chance_of_playing_next_round','news','news_added')
        changed = {k:{'before':prior.get(k),'after':row.get(k)} for k in fields
                   if prior.get(k)!=row.get(k)}
        if changed:
            changes.append({'player_id':int(pid),'player':row.get('web_name'),
                            'team_id':row.get('team'),'changes':changed})
    return changes


def player_keys(snapshot: dict) -> dict[str, list[int]]:
    names = {}
    for p in snapshot.get('players',{}).values():
        full = ' '.join(str(p.get(k) or '').strip() for k in ('first_name','second_name')).strip()
        # Avoid ambiguous surname-only matching and common one-word web_names.
        if len(full.split()) < 2 or len(full) < 7:
            continue
        names.setdefault(full.casefold(),[]).append(int(p['id']))
    return {k:v for k,v in names.items() if len(v)==1}


def parse_feed(xml: bytes, names: dict[str,list[int]], now: datetime, max_age_days=3) -> list[dict]:
    root = ET.fromstring(xml)
    entries = root.findall('.//item')[:80]
    out = []
    for item in entries:
        title = (item.findtext('title') or '').strip()
        link = (item.findtext('link') or '').strip()
        raw_pub = item.findtext('pubDate') or ''
        try:
            pub = parsedate_to_datetime(raw_pub).astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            continue
        if not (0 <= (now-pub).total_seconds() <= 86400*max_age_days):
            continue
        if not link.startswith('https://'):
            continue
        matched = [v[0] for full,v in names.items()
                   if re.search(r'(?<!\w)'+re.escape(full)+r'(?!\w)',title,re.I)]
        if len(set(matched))!=1:
            continue
        out.append({'player_id':matched[0],'title':title[:180],
                    'url':link, 'published_at':pub.isoformat(),
                    'verification':'unverified_candidate',
                    'note':'Headline alone must NOT affect xP or availability'})
    return out[:80]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    temp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir',default='data')
    parser.add_argument('--skip-feeds',action='store_true')
    args = parser.parse_args()
    folder = Path(args.data_dir)
    now = datetime.now(timezone.utc)
    previous_path = folder/'player_monitor.json'
    try:
        previous = json.loads(previous_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        previous = {}
    current = player_snapshot(json.loads(fetch(BASE)),now.isoformat())
    changes = compare(previous,current)
    if previous.get('players') != current['players']:
        write_json(previous_path,current)
        write_json(folder/'fpl_changes.json',{'updated_at':now.isoformat(),
                                              'changes':changes})
    # News is a review inbox, NOT an automatic availability authority.
    inbox = []
    if not args.skip_feeds:
        for url in DEFAULT_FEEDS:
            try:
                inbox.extend(parse_feed(fetch(url,1_500_000),player_keys(current),now))
            except Exception as exc:
                print('News feed unavailable (FPL monitor succeeded):',type(exc).__name__)
    news_path = folder/'news_candidates.json'
    try:
        prior_news = json.loads(news_path.read_text(encoding='utf-8'))
    except (OSError,ValueError):
        prior_news = {}
    if prior_news.get('candidates') != inbox[:80]:
        write_json(news_path,{'updated_at':now.isoformat(),
                              'status':'review_only','candidates':inbox[:80]})
    print('Monitored',len(current['players']),'players;',len(changes),
          'FPL changes;',len(inbox),'news candidates for review')


if __name__ == '__main__':
    main()
