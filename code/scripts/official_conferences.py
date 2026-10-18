"""Public official lists complement bibliographic indexes; never infer a day from a year."""
import asyncio
import html
import json
import re
import copy
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, parse_qs
from backend.models import now
from backend.sources import SourceError, doi_id, arxiv_id
from scripts.public_records import PublicRecord


class Links(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.links=[];self.current=None;self.feed(text)
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='a' and attrs.get('href'): self.current=[attrs['href'],'']
    def handle_data(self, data):
        if self.current is not None:self.current[1]+=data
    def handle_endtag(self, tag):
        if tag=='a' and self.current is not None:
            self.links.append((self.current[0],' '.join(self.current[1].split())));self.current=None


def registry(year):
    return {
        'NeurIPS':('virtual',f'https://neurips.cc/virtual/{year}/'+('loc/sydney/papers.html' if year==2026 else 'papers.html')),
        'ICML':('virtual',f'https://icml.cc/virtual/{year}/papers.html'),
        'ICLR':('virtual',f'https://iclr.cc/virtual/{year}/papers.html'),
        'CVPR':('cvf',f'https://openaccess.thecvf.com/CVPR{year}?day=all'),
        'ICCV':('cvf',f'https://openaccess.thecvf.com/ICCV{year if year%2 else year-1}?day=all'),
        'ECCV':('cvf','https://www.ecva.net/papers.php'),
        'ACL':('acl',f'https://aclanthology.org/events/acl-{year}/'),
        'EMNLP':('acl',f'https://aclanthology.org/events/emnlp-{year}/'),
        'AAAI':('aaai','https://ojs.aaai.org/index.php/AAAI/issue/archive'),
        'IJCAI':('ijcai',f'https://www.ijcai.org/proceedings/{year}/'),
        'KDD':('kdd',f'https://kdd{year}.kdd.org/papers/'),
    }


def record(name, year, url, title, **kwargs):
    return PublicRecord(source='conferences',source_id='official:'+url,title=html.unescape(title).strip(),
        url=url,conference=name,venue=f'{name} {year} · 官方公开清单',publication_year=year,
        index_provider=name+' 官网',retrieved_at=now(),**kwargs)


def parse_virtual(payload, name, year, base):
    rows=payload.get('results')
    if not isinstance(rows,list):raise ValueError('Missing official results')
    records=[]
    for row in rows:
        if row.get('visible') is False or not row.get('name') or not row.get('virtualsite_url'):continue
        url=urljoin(base,row['virtualsite_url'])
        if urlparse(url).netloc!=urlparse(base).netloc or f'/virtual/{year}/' not in urlparse(url).path:continue
        paper=row.get('paper_url') or ''
        related=[]
        if urlparse(paper).netloc=='openreview.net':
            identifier=parse_qs(urlparse(paper).query).get('id',[''])[0]
            if re.fullmatch(r'[\w-]+',identifier):related=['openreview:'+identifier]
        records.append(record(name,year,url,row['name'],authors=[a['fullname'] for a in row.get('authors',[]) if a.get('fullname')],
            doi=doi_id(paper) if 'doi.org/' in paper else None, arxiv_id=arxiv_id(paper),
            pdf_url=row.get('paper_pdf_url'),related_ids=related))
    return list({r.source_id:r for r in records}.values())


def parse_html(body, name, year, base, kind):
    records=[]
    if kind=='cvf':
        for block in re.split(r'<dt\b[^>]*class=["\']ptitle["\'][^>]*>',body,flags=re.I)[1:]:
            links=Links(block).links
            candidates=[(urljoin(base,u),t) for u,t in links if re.search(r'_paper\.(?:html|php)',u) and t]
            if not candidates:continue
            url,title=candidates[0]
            years=re.findall(r'(?:ECCV|ICCV|CVPR)[_/]?(\d{4})',url,re.I)
            if not years:continue
            itemyear=int(years[-1]);doi=None;pdf=None
            for u,t in links:
                if t.lower()=='doi':doi=doi_id(urljoin(base,u).split('/chapter/')[-1])
                if t.lower()=='pdf':pdf=urljoin(base,u)
            authors=re.findall(r'name=["\']query_author["\']\s+value=["\']([^"\']+)',block)
            records.append(record(name,itemyear,url,title,authors=[html.unescape(a) for a in authors],doi=doi,pdf_url=pdf))
    elif kind=='ijcai':
        for block in re.split(r'<div\b[^>]*class=["\']paper_wrapper["\'][^>]*>',body)[1:]:
            title=re.search(r'<div class="title">(.*?)</div>',block,re.S)
            links=Links(block).links
            detail=next((urljoin(base,u) for u,t in links if re.search(r'/proceedings/\d{4}/\d+$',u)),None)
            if title and detail:
                itemyear=int(re.search(r'/proceedings/(\d{4})/',detail)[1])
                authors=re.search(r'<div class="authors">(.*?)</div>',block,re.S)
                number=detail.rsplit('/',1)[-1]
                records.append(record(name,itemyear,detail,html.unescape(re.sub('<[^>]+>','',title[1])),
                    authors=html.unescape(authors[1]).split(', ') if authors else [],
                    doi=f'10.24963/ijcai.{itemyear}/{number}',pdf_url=next((urljoin(base,u) for u,t in links if t=='PDF'),None)))
    elif kind in ('acl','aaai'):
        for u,title in Links(body).links:
            url=urljoin(base,u)
            match=re.search(r'/(\d{4})\.(acl|emnlp)-(long|short|main)\.\d+/$',url) if kind=='acl' else re.search(r'/AAAI/article/view/\d+/?$',url)
            if match and len(title)>10 and title.lower() not in ('abstract','download pdf') and not re.search(r'\.0/$',url):
                records.append(record(name,int(match[1]) if kind=='acl' else year,url,title))
    elif kind=='kdd':
        if not re.search(rf'KDD[\s-]*{year}',body,re.I):return []
        for match in re.finditer(r'const\s+cycle\d+Papers\s*=\s*',body):
            rows,_=json.JSONDecoder().raw_decode(body[match.end():])
            for row in rows:
                url=row.get('url','')
                if urlparse(url).netloc!='doi.org' or not row.get('title'):continue
                authors=[re.sub(r'\s*\(.*\)\s*$','',a).strip() for a in row.get('authors','').split(';') if a.strip()]
                records.append(record(name,year,url,row['title'],authors=authors,doi=doi_id(url)))
    return list({r.source_id:r for r in records}.values())


async def fetch_text(client,url):
    async with client.stream('GET',url,timeout=60,follow_redirects=True) as response:
        if response.status_code!=200:raise SourceError('official_unavailable',f'官网返回 HTTP {response.status_code}，未取得该入口清单。')
        body=bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body)>64*1024*1024:raise SourceError('response_too_large','官方单份清单过大，未标为收齐。')
    return body.decode('utf-8')


def discovered_entries(body, root, year):
    host=urlparse(root).hostname
    result=[]
    for href,title in Links(body).links:
        url=urljoin(root,href);parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname!=host:continue
        if str(year) in url and re.search(r'papers|accepted|proceedings',url+' '+title,re.I):result.append(url)
    return list(dict.fromkeys(result))


async def entry_page(client,url,year):
    try:return url,await fetch_text(client,url)
    except SourceError as exc:
        if 'HTTP 404' not in exc.message:raise
        # Follow actual official links; do not silently substitute an older year.
        root=f'https://{urlparse(url).netloc}/'
        body=await fetch_text(client,root)
        for candidate in discovered_entries(body,root,year):
            if candidate!=url:
                try:return candidate,await fetch_text(client,candidate)
                except SourceError:continue
        raise SourceError('entry_changed',f'{year} 年官方入口待更新或尚未公开；官网首页未发现可用的新入口。')


async def collect_official(client, year, previous=None, day=None):
    state=copy.deepcopy(previous or {})
    day=day or str(date.today())
    semaphore=asyncio.Semaphore(3)
    async def one(name,kind,url):
        entry=state.setdefault(name,{'year':year})
        if entry.get('year')!=year:state[name]=entry={'year':year}
        if entry.get('checked_date')==day and entry.get('report'):
            return [],{**entry['report'],'cached':True}
        rows=[]
        try:
            async with semaphore:
                url,body=await entry_page(client,url,year)
                if kind=='virtual':
                    paths=re.findall(r'["\']([^"\']+orals-posters\.json)["\']',body)
                    if not paths:raise SourceError('missing_schema','官方页面未暴露已支持的论文清单格式。')
                    target=urljoin(url,paths[0])
                    if urlparse(target).netloc!=urlparse(url).netloc:raise ValueError('External index')
                    payload=json.loads(await fetch_text(client,target))
                    rows=parse_virtual(payload,name,year,url)
                    if payload.get('next'):raise SourceError('incomplete_page','官方清单仍有分页，当前覆盖尚未完成。')
                elif kind=='aaai':
                    # Follow only issues explicitly labelled with the current year.
                    issues=[]
                    visited=set()
                    while True:
                        for block in re.split(r'<div[^>]*class="[^\"]*obj_issue_summary[^\"]*"[^>]*>',body)[1:]:
                            if re.search(rf'AAAI-{str(year)[2:]}\s',block):
                                issues.extend(urljoin(url,u) for u,t in Links(block).links if '/AAAI/issue/view/' in u)
                        following=next((urljoin(url,u) for u,t in Links(body).links if '/AAAI/issue/archive/' in u and ('next' in t.lower() or '下一' in t)),None)
                        if not following or following in visited or not re.search(rf'AAAI-{str(year)[2:]}\s',body):break
                        visited.add(following);body=await fetch_text(client,following)
                    if not issues:raise SourceError('missing_schema','尚未识别当前年度的官方卷期入口。')
                    if entry.get('report',{}).get('state')=='success':entry['issues']={}
                    done=entry.setdefault('issues',{})
                    for issue in dict.fromkeys(issues):
                        if issue in done:continue
                        batch=parse_html(await fetch_text(client,issue),name,year,issue,kind)
                        if not batch:raise SourceError('missing_schema','卷期未识别到论文，保留未完成状态。')
                        rows.extend(batch);done[issue]=len(batch)
                else:rows=parse_html(body,name,year,url,kind)
                if not rows and not (kind=='aaai' and entry.get('issues')):raise SourceError('missing_schema','官网可访问，但尚未取得可验证的逐篇清单；未标为收齐。')
                years=sorted({r.publication_year for r in rows}) or [year]
                current=year-1 if (name=='ICCV' and not year%2) or (name=='ECCV' and year%2) else year
                status='success' if current in years else 'partial'
                note='已读取该官方清单；覆盖年份 '+', '.join(map(str,years))+'。仅说明此入口，不代表全会议或全网收齐。'
            report={'label':name+' 官网','conference':name,'index':'Official','url':url,'state':status,'count':sum(entry.get('issues',{}).values()) if kind=='aaai' else len(rows),'note':note}
        except Exception as exc:
            report={'label':name+' 官网','conference':name,'index':'Official','url':url,'state':'partial' if rows else 'error','count':len(rows),
                'note':exc.message if isinstance(exc,SourceError) else '官方入口请求或解析失败；保留历史数据，稍后重试。'}
        entry.update(checked_date=day,report=report)
        return rows,report
    results=await asyncio.gather(*(one(name,kind,url) for name,(kind,url) in registry(year).items()))
    return [r for rows,_ in results for r in rows],[report for _,report in results],state
