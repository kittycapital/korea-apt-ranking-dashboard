"""
전국 아파트 대시보드 통합 데이터 수집기
─────────────────────────────────────
하나의 API 호출 세트로 두 가지 대시보드 데이터를 모두 생성:
  1) 전국 구별 TOP 10  → data/district_top10.json  (index.html 에서 사용)
  2) 서울 아파트 TOP 20 → seoul.html               (인라인 데이터)

- 데이터: 국토교통부 아파트 매매 실거래가 API
- 필터: 전용면적 59㎡ 이상
- 기간: TOP 산정 최근 6개월 / 추이 차트 최근 3년
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from collections import defaultdict
import os, json, time, re

# ── 설정 ──
API_KEY = os.environ.get('MOLIT_API_KEY', '')
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
BASE_URL = "http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
DATA_DIR = 'data'
MIN_AREA = 59

# API 호출 간 대기 (초) — 레이트 리밋 방지
DELAY_PER_REQUEST = 0.5    # 매 요청 후 대기
DELAY_PER_REGION = 1.0     # 지역 완료 후 추가 대기
RETRY_BASE_DELAY = 10      # 429 에러 시 기본 대기 (10, 20, 40, 80, 160초 백오프)

# ── 전국 지역코드 (서울 + 전국) ──
REGIONS = {
    # 서울시 (25)
    '11110':('서울시','종로구'),'11140':('서울시','중구'),'11170':('서울시','용산구'),
    '11200':('서울시','성동구'),'11215':('서울시','광진구'),'11230':('서울시','동대문구'),
    '11260':('서울시','중랑구'),'11290':('서울시','성북구'),'11305':('서울시','강북구'),
    '11320':('서울시','도봉구'),'11350':('서울시','노원구'),'11380':('서울시','은평구'),
    '11410':('서울시','서대문구'),'11440':('서울시','마포구'),'11470':('서울시','양천구'),
    '11500':('서울시','강서구'),'11530':('서울시','구로구'),'11545':('서울시','금천구'),
    '11560':('서울시','영등포구'),'11590':('서울시','동작구'),'11620':('서울시','관악구'),
    '11650':('서울시','서초구'),'11680':('서울시','강남구'),'11710':('서울시','송파구'),
    '11740':('서울시','강동구'),
    # 부산시
    '26110':('부산시','중구'),'26140':('부산시','서구'),'26170':('부산시','동구'),
    '26200':('부산시','영도구'),'26230':('부산시','부산진구'),'26260':('부산시','동래구'),
    '26290':('부산시','남구'),'26320':('부산시','북구'),'26350':('부산시','해운대구'),
    '26380':('부산시','사하구'),'26410':('부산시','금정구'),'26440':('부산시','강서구'),
    '26470':('부산시','연제구'),'26500':('부산시','수영구'),'26530':('부산시','사상구'),
    '26710':('부산시','기장군'),
    # 대구시
    '27110':('대구시','중구'),'27140':('대구시','동구'),'27170':('대구시','서구'),
    '27200':('대구시','남구'),'27230':('대구시','북구'),'27260':('대구시','수성구'),
    '27290':('대구시','달서구'),'27710':('대구시','달성군'),'27720':('대구시','군위군'),
    # 인천시
    '28110':('인천시','중구'),'28140':('인천시','동구'),'28177':('인천시','미추홀구'),
    '28185':('인천시','연수구'),'28200':('인천시','남동구'),'28237':('인천시','부평구'),
    '28245':('인천시','계양구'),'28260':('인천시','서구'),'28710':('인천시','강화군'),
    '28720':('인천시','옹진군'),
    # 광주시
    '29110':('광주시','동구'),'29140':('광주시','서구'),'29155':('광주시','남구'),
    '29170':('광주시','북구'),'29200':('광주시','광산구'),
    # 대전시
    '30110':('대전시','동구'),'30140':('대전시','중구'),'30170':('대전시','서구'),
    '30200':('대전시','유성구'),'30230':('대전시','대덕구'),
    # 울산시
    '31110':('울산시','중구'),'31140':('울산시','남구'),'31170':('울산시','동구'),
    '31200':('울산시','북구'),'31710':('울산시','울주군'),
    # 세종시
    '36110':('세종시','세종시'),
    # 경기도
    '41111':('경기도','수원시 장안구'),'41113':('경기도','수원시 권선구'),
    '41115':('경기도','수원시 팔달구'),'41117':('경기도','수원시 영통구'),
    '41131':('경기도','성남시 수정구'),'41133':('경기도','성남시 중원구'),
    '41135':('경기도','성남시 분당구'),'41150':('경기도','의정부시'),
    '41171':('경기도','안양시 만안구'),'41173':('경기도','안양시 동안구'),
    '41190':('경기도','부천시'),'41210':('경기도','광명시'),
    '41220':('경기도','평택시'),'41250':('경기도','동두천시'),
    '41271':('경기도','안산시 상록구'),'41273':('경기도','안산시 단원구'),
    '41281':('경기도','고양시 덕양구'),'41285':('경기도','고양시 일산동구'),
    '41287':('경기도','고양시 일산서구'),'41290':('경기도','과천시'),
    '41310':('경기도','구리시'),'41360':('경기도','남양주시'),
    '41370':('경기도','오산시'),'41390':('경기도','시흥시'),
    '41410':('경기도','군포시'),'41430':('경기도','의왕시'),
    '41450':('경기도','하남시'),'41461':('경기도','용인시 처인구'),
    '41463':('경기도','용인시 기흥구'),'41465':('경기도','용인시 수지구'),
    '41480':('경기도','파주시'),'41500':('경기도','이천시'),
    '41550':('경기도','안성시'),'41570':('경기도','김포시'),
    '41590':('경기도','화성시'),'41610':('경기도','광주시'),
    '41630':('경기도','양주시'),'41650':('경기도','포천시'),
    '41670':('경기도','여주시'),'41800':('경기도','연천군'),
    '41820':('경기도','가평군'),'41830':('경기도','양평군'),
    # 강원도
    '51110':('강원도','춘천시'),'51130':('강원도','원주시'),
    '51150':('강원도','강릉시'),'51170':('강원도','동해시'),
    '51190':('강원도','태백시'),'51210':('강원도','속초시'),
    '51230':('강원도','삼척시'),'51710':('강원도','홍천군'),
    '51720':('강원도','횡성군'),'51730':('강원도','영월군'),
    '51740':('강원도','평창군'),'51750':('강원도','정선군'),
    '51760':('강원도','철원군'),'51770':('강원도','화천군'),
    '51780':('강원도','양구군'),'51790':('강원도','인제군'),
    '51800':('강원도','고성군'),'51810':('강원도','양양군'),
    # 충북
    '43111':('충북','청주시 상당구'),'43112':('충북','청주시 서원구'),
    '43113':('충북','청주시 흥덕구'),'43114':('충북','청주시 청원구'),
    '43130':('충북','충주시'),'43150':('충북','제천시'),
    '43720':('충북','보은군'),'43730':('충북','옥천군'),
    '43740':('충북','영동군'),'43745':('충북','증평군'),
    '43750':('충북','진천군'),'43760':('충북','괴산군'),
    '43770':('충북','음성군'),'43800':('충북','단양군'),
    # 충남
    '44131':('충남','천안시 동남구'),'44133':('충남','천안시 서북구'),
    '44150':('충남','공주시'),'44180':('충남','보령시'),
    '44200':('충남','아산시'),'44210':('충남','서산시'),
    '44230':('충남','논산시'),'44250':('충남','계룡시'),
    '44270':('충남','당진시'),'44710':('충남','금산군'),
    '44760':('충남','부여군'),'44770':('충남','서천군'),
    '44790':('충남','청양군'),'44800':('충남','홍성군'),
    '44810':('충남','예산군'),'44825':('충남','태안군'),
    # 전북
    '52111':('전북','전주시 완산구'),'52113':('전북','전주시 덕진구'),
    '52130':('전북','군산시'),'52140':('전북','익산시'),
    '52180':('전북','정읍시'),'52190':('전북','남원시'),
    '52210':('전북','김제시'),'52710':('전북','완주군'),
    '52720':('전북','진안군'),'52730':('전북','무주군'),
    '52740':('전북','장수군'),'52750':('전북','임실군'),
    '52770':('전북','순창군'),'52790':('전북','고창군'),
    '52800':('전북','부안군'),
    # 전남
    '46110':('전남','목포시'),'46130':('전남','여수시'),
    '46150':('전남','순천시'),'46170':('전남','나주시'),
    '46230':('전남','광양시'),'46710':('전남','담양군'),
    '46720':('전남','곡성군'),'46730':('전남','구례군'),
    '46770':('전남','고흥군'),'46780':('전남','보성군'),
    '46790':('전남','화순군'),'46800':('전남','장흥군'),
    '46810':('전남','강진군'),'46820':('전남','해남군'),
    '46830':('전남','영암군'),'46840':('전남','무안군'),
    '46860':('전남','함평군'),'46870':('전남','영광군'),
    '46880':('전남','장성군'),'46890':('전남','완도군'),
    '46900':('전남','진도군'),'46910':('전남','신안군'),
    # 경북
    '47111':('경북','포항시 남구'),'47113':('경북','포항시 북구'),
    '47130':('경북','경주시'),'47150':('경북','김천시'),
    '47170':('경북','안동시'),'47190':('경북','구미시'),
    '47210':('경북','영주시'),'47230':('경북','영천시'),
    '47250':('경북','상주시'),'47280':('경북','문경시'),
    '47290':('경북','경산시'),'47720':('경북','의성군'),
    '47730':('경북','청송군'),'47750':('경북','영양군'),
    '47760':('경북','영덕군'),'47770':('경북','청도군'),
    '47820':('경북','고령군'),'47830':('경북','성주군'),
    '47840':('경북','칠곡군'),'47850':('경북','예천군'),
    '47900':('경북','봉화군'),'47920':('경북','울진군'),
    '47930':('경북','울릉군'),
    # 경남
    '48121':('경남','창원시 의창구'),'48123':('경남','창원시 성산구'),
    '48125':('경남','창원시 마산합포구'),'48127':('경남','창원시 마산회원구'),
    '48129':('경남','창원시 진해구'),'48170':('경남','진주시'),
    '48220':('경남','통영시'),'48240':('경남','사천시'),
    '48250':('경남','김해시'),'48270':('경남','밀양시'),
    '48310':('경남','거제시'),'48330':('경남','양산시'),
    '48720':('경남','의령군'),'48730':('경남','함안군'),
    '48740':('경남','창녕군'),'48820':('경남','고성군'),
    '48840':('경남','남해군'),'48850':('경남','하동군'),
    '48860':('경남','산청군'),'48870':('경남','함양군'),
    '48880':('경남','거창군'),'48890':('경남','합천군'),
    # 제주도
    '50110':('제주도','제주시'),'50130':('제주도','서귀포시'),
}

# 서울 지역코드 (서울 TOP 20용)
SEOUL_CODES = {k for k, v in REGIONS.items() if v[0] == '서울시'}


# ════════════════════════════════════════
# 공통 유틸
# ════════════════════════════════════════

def get_months(n):
    months = set()
    today = datetime.today()
    for i in range(n):
        d = today.replace(day=1) - timedelta(days=30*i)
        months.add(d.strftime('%Y%m'))
    return sorted(months)


def fetch(code, ym, retries=5):
    """단일 API 호출 (429 레이트 리밋 자동 재시도)"""
    params = {
        'serviceKey': API_KEY, 'LAWD_CD': code,
        'DEAL_YMD': ym, 'pageNo': '1', 'numOfRows': '9999'
    }
    for attempt in range(retries):
        try:
            r = requests.get(BASE_URL, params=params, timeout=30)
            # 429 Too Many Requests → 대기 후 재시도
            if r.status_code == 429:
                wait = RETRY_BASE_DELAY * (2 ** attempt)  # 10, 20, 40, 80, 160초
                print(f"  ⏳ 429 Rate limit [{code}/{ym}] → {wait}초 대기 (재시도 {attempt+1}/{retries})")
                time.sleep(wait)
                continue
            r.raise_for_status()
            # API 에러 체크
            rc = re.search(r'<resultCode>(\d+)</resultCode>', r.text)
            rm = re.search(r'<resultMsg>([^<]+)</resultMsg>', r.text)
            if rc and rc.group(1) not in ('00', '000'):
                print(f"  ⚠️ API Error [{code}/{ym}]: {rc.group(1)} - {rm.group(1) if rm else 'unknown'}")
                return []
            time.sleep(DELAY_PER_REQUEST)
            return parse(r.text, code)
        except requests.exceptions.HTTPError as e:
            if '429' in str(e):
                wait = RETRY_BASE_DELAY * (2 ** attempt)
                print(f"  ⏳ 429 Rate limit [{code}/{ym}] → {wait}초 대기 (재시도 {attempt+1}/{retries})")
                time.sleep(wait)
                continue
            print(f"  ❌ Request failed [{code}/{ym}]: {e}")
            return []
        except Exception as e:
            print(f"  ❌ Request failed [{code}/{ym}]: {e}")
            return []
    print(f"  ❌ 재시도 초과 [{code}/{ym}]")
    return []


def parse(xml_text, code):
    items = []
    try:
        root = ET.fromstring(xml_text)
        for it in root.findall('.//item'):
            area = float(gt(it, 'excluUseAr', '0'))
            if area < MIN_AREA:
                continue
            ps = gt(it, 'dealAmount', '0').replace(',', '').strip()
            try:
                price = int(ps)
            except:
                continue
            sido, sigungu = REGIONS.get(code, ('', ''))
            items.append({
                'apt_name': gt(it, 'aptNm', ''),
                'sido': sido, 'sigungu': sigungu,
                'dong': gt(it, 'umdNm', ''),
                'area_m2': area, 'area_pyeong': round(area / 3.3, 1),
                'price': price,
                'price_per_pyeong': round((price / area) * 3.3),
                'deal_year': gt(it, 'dealYear', ''),
                'deal_month': gt(it, 'dealMonth', ''),
                'deal_day': gt(it, 'dealDay', ''),
                'floor': gt(it, 'floor', ''),
                'build_year': gt(it, 'buildYear', ''),
                'region_code': code
            })
    except:
        pass
    return items


def gt(el, tag, d=''):
    c = el.find(tag)
    return c.text.strip() if c is not None and c.text else d


def fb(p):
    b = p / 10000
    if b >= 1:
        return f"{int(b)}억" if b == int(b) else f"{b:.1f}억"
    return f"{p:,}만"


def fp(p):
    b = p // 10000
    r = p % 10000
    return f"{b}억 {r:,}만" if b > 0 else f"{p:,}만"


# ════════════════════════════════════════
# Step 1: 데이터 수집 (한 번만)
# ════════════════════════════════════════

def fetch_all_recent(months_6):
    """전 지역 최근 6개월 데이터 수집"""
    print(f"Step 1: 전 지역 6개월 데이터 수집 ({months_6[0]}~{months_6[-1]})")
    print(f"  → {len(REGIONS)}개 지역 × {len(months_6)}개월 = 예상 {len(REGIONS)*len(months_6)}건 API 호출\n")

    recent = []
    total = len(REGIONS)
    for i, (code, (s, g)) in enumerate(REGIONS.items(), 1):
        for m in months_6:
            recent.extend(fetch(code, m))
        if i % 10 == 0:
            print(f"  [{i}/{total}] {s} {g}...")
            time.sleep(DELAY_PER_REGION)
    print(f"  → 총 {len(recent)}건 수집 완료\n")
    return recent


def fetch_history(codes_needed, months_extra):
    """필요한 지역의 히스토리 데이터 추가 수집"""
    print(f"Step 2: 히스토리 수집 ({len(months_extra)}개월 × {len(codes_needed)}개 지역)")
    history = []
    done = 0
    for code in codes_needed:
        for m in months_extra:
            history.extend(fetch(code, m))
        done += 1
        if done % 5 == 0:
            print(f"  [{done}/{len(codes_needed)}]...")
            time.sleep(DELAY_PER_REGION)
    print(f"  → {len(history)}건 추가 수집\n")
    return history


# ════════════════════════════════════════
# 대시보드 1: 전국 구별 TOP 10
# ════════════════════════════════════════

def build_district_data(recent, alldata, months_6_set):
    """전국 구별 TOP 10 JSON 생성"""
    print("── 전국 구별 TOP 10 생성 ──")

    # 구별 그룹핑 (최근 6개월)
    by_district = defaultdict(list)
    for it in recent:
        key = f"{it['sido']}|{it['sigungu']}"
        by_district[key].append(it)

    # 구별 TOP 10
    top10_map = {}
    for key, items in by_district.items():
        best = {}
        for it in items:
            aname = it['apt_name']
            if aname not in best or it['price_per_pyeong'] > best[aname]['price_per_pyeong']:
                best[aname] = it
        t10 = sorted(best.values(), key=lambda x: x['price_per_pyeong'], reverse=True)[:10]
        if t10:
            top10_map[key] = t10

    # 전체 월별 라벨
    all_months_set = set()
    for it in alldata:
        ym = f"{it['deal_year']}.{it['deal_month'].zfill(2)}"
        all_months_set.add(ym)
    all_months = sorted(all_months_set)

    # 구별 전체 데이터
    district_all = defaultdict(list)
    for it in alldata:
        key = f"{it['sido']}|{it['sigungu']}"
        district_all[key].append(it)

    result = {
        "updated": datetime.now().strftime('%Y.%m.%d %H:%M'),
        "labels": all_months,
        "data": {}
    }

    for key, t10 in top10_map.items():
        all_items = district_all[key]

        # 아파트별 월평균 평당가
        apt_monthly = defaultdict(lambda: defaultdict(list))
        for it in all_items:
            ym = f"{it['deal_year']}.{it['deal_month'].zfill(2)}"
            apt_monthly[it['apt_name']][ym].append(it['price_per_pyeong'])

        series = []
        for apt in t10:
            vals = []
            for m in all_months:
                if m in apt_monthly[apt['apt_name']]:
                    v = apt_monthly[apt['apt_name']][m]
                    vals.append(round(sum(v) / len(v)))
                else:
                    vals.append(None)
            series.append(vals)

        # 6개월 거래 건수
        deal_count = sum(
            1 for it in all_items
            if f"{it['deal_year']}{it['deal_month'].zfill(2)}" in months_6_set
        )

        avg_pp = round(sum(it['price_per_pyeong'] for it in t10) / len(t10))

        result["data"][key] = {
            "top10": [{
                "name": it['apt_name'],
                "dong": it['dong'],
                "area_m2": it['area_m2'],
                "area_pyeong": it['area_pyeong'],
                "price": it['price'],
                "ppyeong": it['price_per_pyeong'],
                "date": f"{it['deal_year']}.{it['deal_month'].zfill(2)}.{it['deal_day'].zfill(2)}",
                "floor": it['floor'],
                "build_year": it['build_year']
            } for it in t10],
            "series": series,
            "avg": avg_pp,
            "deals": deal_count
        }

    outpath = os.path.join(DATA_DIR, 'district_top10.json')
    with open(outpath, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)

    fsize = os.path.getsize(outpath) / 1024
    print(f"  → {len(top10_map)}개 지역 → {outpath} ({fsize:.0f}KB)")
    return top10_map


# ════════════════════════════════════════
# 대시보드 2: 서울 TOP 20
# ════════════════════════════════════════

def seoul_top20(data):
    best = defaultdict(lambda: None)
    for it in data:
        k = (it['apt_name'], it['sido'], it['sigungu'])
        if best[k] is None or it['price_per_pyeong'] > best[k]['price_per_pyeong']:
            best[k] = it
    return sorted(best.values(), key=lambda x: x['price_per_pyeong'], reverse=True)[:20]


def seoul_monthly_avg(data, keys):
    m = defaultdict(list)
    for it in data:
        k = (it['apt_name'], it['sido'], it['sigungu'])
        if k in keys:
            ym = f"{it['deal_year']}.{it['deal_month'].zfill(2)}"
            m[ym].append(it['price_per_pyeong'])
    return {ym: round(sum(v) / len(v)) for ym, v in sorted(m.items())}


def seoul_per_apt_monthly(data, t20):
    all_months = set()
    apt_data = defaultdict(lambda: defaultdict(list))
    keys = set((it['apt_name'], it['sido'], it['sigungu']) for it in t20)
    for it in data:
        k = (it['apt_name'], it['sido'], it['sigungu'])
        if k in keys:
            ym = f"{it['deal_year']}.{it['deal_month'].zfill(2)}"
            all_months.add(ym)
            apt_data[k][ym].append(it['price_per_pyeong'])
    months = sorted(all_months)
    result = []
    for it in t20:
        k = (it['apt_name'], it['sido'], it['sigungu'])
        vals = []
        for m in months:
            if m in apt_data[k]:
                vals.append(round(sum(apt_data[k][m]) / len(apt_data[k][m])))
            else:
                vals.append(None)
        result.append({'name': it['apt_name'], 'values': vals})
    return months, result


def seoul_region_dist(t20):
    d = defaultdict(int)
    for it in t20:
        d[it['sigungu']] += 1
    return dict(sorted(d.items(), key=lambda x: x[1], reverse=True))


def seoul_rank_changes(t20, f):
    prev = {}
    if os.path.exists(f):
        with open(f, 'r', encoding='utf-8') as fp_:
            prev = json.load(fp_)
    ch = []
    for i, it in enumerate(t20):
        k = f"{it['apt_name']}|{it['sido']}|{it['sigungu']}"
        p = prev.get(k)
        ch.append('new' if p is None else p - (i + 1))
    cur = {f"{it['apt_name']}|{it['sido']}|{it['sigungu']}": i + 1 for i, it in enumerate(t20)}
    with open(f, 'w', encoding='utf-8') as fp_:
        json.dump(cur, fp_, ensure_ascii=False)
    return ch


def seoul_insights(t20, mavg):
    ms = sorted(mavg.keys())
    avg = round(sum(it['price_per_pyeong'] for it in t20) / len(t20))
    mom = 0
    if len(ms) >= 2:
        c, p = mavg[ms[-1]], mavg[ms[-2]]
        mom = round((c - p) / p * 100, 1) if p > 0 else 0
    rd = seoul_region_dist(t20)
    streak = 0
    direction = 'flat'
    if len(ms) >= 2:
        for i in range(len(ms) - 1, 0, -1):
            diff = mavg[ms[i]] - mavg[ms[i - 1]]
            if streak == 0:
                direction = 'up' if diff > 0 else 'down'
                streak = 1
            elif (direction == 'up' and diff > 0) or (direction == 'down' and diff < 0):
                streak += 1
            else:
                break
    return {
        'avg': avg, 'mom': mom,
        'top_apt': t20[0]['apt_name'], 'top_apt_price': t20[0]['price_per_pyeong'],
        'top_region': list(rd.keys())[0], 'top_region_count': list(rd.values())[0],
        'streak': streak, 'direction': direction
    }


def build_seoul_html(recent_seoul, alldata_seoul):
    """서울 TOP 20 HTML 대시보드 생성"""
    print("\n── 서울 TOP 20 생성 ──")

    t20 = seoul_top20(recent_seoul)
    if not t20:
        print("  ⚠️ 서울 데이터 없음, 건너뜀")
        return

    keys = set((it['apt_name'], it['sido'], it['sigungu']) for it in t20)
    mavg = seoul_monthly_avg(alldata_seoul, keys)
    apt_months, apt_series = seoul_per_apt_monthly(alldata_seoul, t20)
    rd = seoul_region_dist(t20)
    rch = seoul_rank_changes(t20, os.path.join(DATA_DIR, 'previous_rank.json'))
    ins = seoul_insights(t20, mavg)

    # JSON 저장
    with open(os.path.join(DATA_DIR, 'top20.json'), 'w', encoding='utf-8') as f:
        json.dump([it for it in t20], f, ensure_ascii=False, indent=2)
    with open(os.path.join(DATA_DIR, 'history.json'), 'w', encoding='utf-8') as f:
        json.dump(mavg, f, ensure_ascii=False, indent=2)

    # HTML 생성
    gkey = GOOGLE_MAPS_API_KEY
    html = gen_seoul_html(t20, rch, mavg, rd, ins, gkey, apt_months, apt_series)
    with open('seoul.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  → seoul.html 생성 완료")
    for i, it in enumerate(t20, 1):
        print(f"  {i}. {it['apt_name']} ({it['sido']} {it['sigungu']}) - {fp(it['price_per_pyeong'])}")


def gen_seoul_html(t20, rch, mavg, rdist, ins, gkey, apt_months, apt_series):
    ut = datetime.now().strftime('%Y.%m.%d %H:%M')
    cl = json.dumps(list(mavg.keys()))
    cv = json.dumps(list(mavg.values()))
    dl = json.dumps(list(rdist.keys()))
    dv = json.dumps(list(rdist.values()))
    colors = ['#00d4aa','#4ecdc4','#ff6b6b','#45b7d1','#96ceb4','#ffeaa7','#dfe6e9','#a29bfe','#fd79a8','#e17055','#00b894','#6c5ce7','#fdcb6e','#e84393','#636e72','#fab1a0','#74b9ff','#55efc4','#b2bec3','#ff7675']
    dc = json.dumps(colors[:len(rdist)])
    af = fp(ins['avg'])
    mom = ins['mom']
    ms = '▲' if mom > 0 else ('▼' if mom < 0 else '─')
    mc = '#00d4aa' if mom > 0 else ('#ff4757' if mom < 0 else '#888')

    tp = []
    if ins['streak'] > 1:
        e = '📈' if ins['direction'] == 'up' else '📉'
        tp.append(f"{e} {ins['streak']}개월 연속 {'상승' if ins['direction'] == 'up' else '하락'} 중")
    for i, rc in enumerate(rch):
        if rc == 'new':
            tp.append(f"🆕 신규 진입: {t20[i]['apt_name']}")
    mvrs = [(i, rc) for i, rc in enumerate(rch) if isinstance(rc, int) and rc != 0]
    if mvrs:
        bu = max(mvrs, key=lambda x: x[1])
        bd = min(mvrs, key=lambda x: x[1])
        if bu[1] > 0:
            tp.append(f"🔥 최대 상승: {t20[bu[0]]['apt_name']} (+{bu[1]}위)")
        if bd[1] < 0:
            tp.append(f"❄️ 최대 하락: {t20[bd[0]]['apt_name']} ({bd[1]}위)")
    th = ' · '.join(tp) if tp else '📊 순위 변동 데이터 수집 중...'

    # Per-apartment chart data
    apt_labels = json.dumps(apt_months)
    apt_datasets_js = "["
    for i, s in enumerate(apt_series):
        c = colors[i % len(colors)]
        vals = json.dumps(s['values'])
        apt_datasets_js += f"""{{
            label:'{s['name']}',data:{vals},borderColor:'{c}',
            backgroundColor:'transparent',tension:0.3,
            pointRadius:0,pointHoverRadius:4,borderWidth:1.5,
            spanGaps:true
        }},"""
    apt_datasets_js += "]"

    rows = ""
    for i, it in enumerate(t20):
        rc = rch[i]
        if rc == 'new':
            ch = '<span style="color:#ffeaa7;font-size:0.8rem;">NEW</span>'
        elif rc > 0:
            ch = f'<span style="color:#00d4aa;">▲{rc}</span>'
        elif rc < 0:
            ch = f'<span style="color:#ff4757;">▼{abs(rc)}</span>'
        else:
            ch = '<span style="color:#888;">─</span>'
        dd = f"{it['deal_year']}.{it['deal_month'].zfill(2)}.{it['deal_day'].zfill(2)}"
        loc = f"{it['sido']} {it['sigungu']}"
        mq = f"{it['apt_name']}+{it['sido']}+{it['sigungu']}+{it['dong']}"
        c = colors[i % len(colors)]
        rows += f'''
        <tr class="main-row" data-idx="{i}" onclick="handleRowClick({i})">
            <td class="rank-cell">{i+1}</td><td class="change-cell">{ch}</td>
            <td class="apt-name"><span class="color-dot" style="background:{c};"></span>{it['apt_name']} <span class="arrow" id="arrow-{i+1}">▼</span></td>
            <td class="loc-cell">{loc}</td><td class="price">{fp(it['price_per_pyeong'])}</td>
        </tr>
        <tr class="detail-row" id="detail-{i+1}"><td colspan="5"><div class="detail-content">
            <div class="detail-info"><table class="detail-table">
                <tr><th>동</th><td>{it['dong']}</td></tr>
                <tr><th>전용면적</th><td>{it['area_m2']}㎡ ({it['area_pyeong']}평)</td></tr>
                <tr><th>거래금액</th><td>{fb(it['price'])}</td></tr>
                <tr><th>거래일</th><td>{dd}</td></tr>
                <tr><th>층</th><td>{it['floor']}층</td></tr>
                <tr><th>건축년도</th><td>{it['build_year']}년</td></tr>
            </table></div>
            <div class="detail-map"><iframe width="300" height="200" style="border:0;border-radius:8px;" loading="lazy" allowfullscreen referrerpolicy="no-referrer-when-downgrade" src="https://www.google.com/maps/embed/v1/place?key={gkey}&q={mq}&zoom=15"></iframe></div>
        </div></td></tr>'''

    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>서울 아파트 평당가 TOP 20</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Noto Sans KR',sans-serif;background:#000;color:#fff;min-height:100vh;padding:40px 20px}}
.container{{max-width:1200px;margin:0 auto}}
h1{{font-size:2rem;font-weight:700;margin-bottom:8px;letter-spacing:-0.5px}}
.subtitle{{color:#888;font-size:0.9rem;margin-bottom:24px}}
.insight-cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}}
.insight-card{{background:#1a1a1a;border-radius:12px;padding:20px}}
.insight-card .label{{color:#888;font-size:0.8rem;margin-bottom:8px}}
.insight-card .value{{font-size:1.3rem;font-weight:700}}
.insight-card .sub{{font-size:0.85rem;margin-top:4px;color:#888}}
.chart-section{{background:#1a1a1a;border-radius:12px;padding:24px;margin-bottom:20px}}
.chart-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:10px}}
.chart-title{{font-size:1rem;font-weight:700}}
.chart-hint{{font-size:0.8rem;color:#555;margin-top:8px;text-align:center}}
.toggle-btns{{display:flex;gap:4px}}
.toggle-btn{{background:#333;border:none;color:#aaa;padding:6px 14px;border-radius:8px;cursor:pointer;font-size:0.8rem;font-family:inherit;transition:all 0.2s}}
.toggle-btn.active{{background:#00d4aa;color:#000}}
.chart-canvas-wrap{{width:100%;height:200px;position:relative}}
.chart-canvas-wrap canvas{{width:100%!important;height:100%!important}}
.selected-label{{position:absolute;top:8px;left:12px;font-size:0.9rem;font-weight:700;color:#00d4aa;opacity:0;transition:opacity 0.3s;pointer-events:none}}
.selected-label.show{{opacity:1}}
.trend-bar{{background:#1a1a1a;border-radius:12px;padding:16px 20px;margin-bottom:20px;font-size:0.9rem;color:#aaa}}
table.main-table{{width:100%;border-collapse:collapse}}
table.main-table thead th{{text-align:left;padding:14px 10px;border-bottom:2px solid #333;font-weight:500;color:#aaa;font-size:0.82rem}}
table.main-table thead th:last-child{{text-align:right}}
.main-row{{cursor:pointer;transition:background 0.25s,opacity 0.25s}}
.main-row:hover{{background:#1a1a1a}}
.main-row td{{padding:16px 10px;border-bottom:1px solid #222;font-size:0.95rem}}
.main-row.active-row{{background:rgba(0,212,170,0.08)}}
.main-row.dimmed{{opacity:0.35}}
.color-dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;vertical-align:middle}}
.rank-cell{{font-weight:700;color:#666;width:40px}}
.change-cell{{width:50px;font-size:0.85rem}}
.apt-name{{font-weight:500}}
.loc-cell{{color:#aaa}}
.arrow{{color:#555;font-size:0.7rem;margin-left:6px;transition:transform 0.2s;display:inline-block}}
.arrow.open{{transform:rotate(180deg)}}
.price{{text-align:right;font-weight:700;color:#00d4aa;font-variant-numeric:tabular-nums}}
.detail-row{{display:none}}
.detail-row.show{{display:table-row}}
.detail-row td{{padding:0;background:#0d0d0d;border-bottom:1px solid #222}}
.detail-content{{padding:20px 10px 20px 50px;display:flex;gap:30px;align-items:flex-start}}
.detail-info{{flex:1}}
.detail-map{{flex-shrink:0}}
.detail-table{{width:100%;max-width:350px}}
.detail-table th{{text-align:left;padding:7px 16px 7px 0;color:#666;font-weight:400;font-size:0.88rem;width:90px}}
.detail-table td{{padding:7px 0;font-size:0.93rem;color:#ccc}}
.footer{{margin-top:40px;padding-top:20px;border-top:1px solid #222;color:#555;font-size:0.8rem;text-align:center}}
@media(max-width:1024px){{.insight-cards{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:600px){{body{{padding:20px 12px}}h1{{font-size:1.4rem}}.insight-cards{{grid-template-columns:1fr 1fr}}.chart-canvas-wrap{{height:180px}}.detail-content{{flex-direction:column;padding:15px 8px 15px 20px;gap:16px}}.detail-map iframe{{width:100%;max-width:300px}}.main-row td{{padding:12px 6px;font-size:0.88rem}}}}
</style>
</head>
<body>
<div class="container">
<h1>서울 아파트 평당가 TOP 20 <span style="font-weight:400;font-size:1rem;color:#888;">(전용면적 기준)</span></h1>
<p class="subtitle">최근 6개월 실거래 기준 · 단지별 최고가</p>

<div class="insight-cards">
<div class="insight-card"><div class="label">TOP 20 평균 평당가</div><div class="value">{af}</div></div>
<div class="insight-card"><div class="label">전월 대비</div><div class="value" style="color:{mc};">{ms} {abs(mom)}%</div></div>
<div class="insight-card"><div class="label">최고가 단지</div><div class="value" style="font-size:1.1rem;">{ins['top_apt']}</div><div class="sub">{fp(ins['top_apt_price'])}</div></div>
<div class="insight-card"><div class="label">최다 지역</div><div class="value" style="font-size:1.1rem;">{ins['top_region']}</div><div class="sub">TOP 20 중 {ins['top_region_count']}개</div></div>
</div>

<div class="chart-section" id="chartSection">
<div class="chart-header">
<span class="chart-title">📈 아파트별 평당가 추이</span>
<div class="toggle-btns">
<button class="toggle-btn" onclick="setRange(12)" id="btn-1y">1년</button>
<button class="toggle-btn" onclick="setRange(24)" id="btn-2y">2년</button>
<button class="toggle-btn active" onclick="setRange(36)" id="btn-3y">3년</button>
</div>
</div>
<div class="chart-canvas-wrap">
<div class="selected-label" id="selectedLabel"></div>
<canvas id="trendChart"></canvas>
</div>
<div class="chart-hint">👆 아래 리스트에서 아파트를 클릭하면 해당 추이가 강조됩니다</div>
</div>

<div class="trend-bar">{th}</div>

<table class="main-table">
<thead><tr><th>순위</th><th></th><th>단지명</th><th>지역</th><th style="text-align:right;">평당가</th></tr></thead>
<tbody>{rows}</tbody>
</table>

<div class="footer">마지막 업데이트: {ut} · 데이터 출처: 국토교통부 실거래가 공개시스템</div>
</div>

<script>
const aptLabels = {apt_labels};
const aptDatasets = {apt_datasets_js};
const avgLabels = {cl};
const avgValues = {cv};

const COLORS = {json.dumps(colors[:20])};

/* ── Chart.js: 아파트별 추이 ── */
const ctx = document.getElementById('trendChart').getContext('2d');
const datasets = aptDatasets.map((d, i) => ({{
    ...d,
    borderColor: COLORS[i],
    borderWidth: 1.5,
    pointRadius: 0,
    pointHoverRadius: 4,
    backgroundColor: 'transparent',
    tension: 0.3,
    spanGaps: true,
    _origColor: COLORS[i]
}}));

const tc = new Chart(ctx, {{
    type: 'line',
    data: {{ labels: aptLabels, datasets: datasets }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{
            legend: {{ display: false }},
            tooltip: {{
                backgroundColor: '#1a1a1a', titleColor: '#fff',
                bodyColor: '#ccc', borderColor: '#333', borderWidth: 1,
                filter: function(item) {{ return item.raw !== null; }},
                callbacks: {{
                    label: function(c) {{
                        if (c.raw === null) return null;
                        const v = c.raw;
                        const b = Math.floor(v / 10000);
                        const r = v % 10000;
                        const p = b > 0 ? b + '억 ' + r.toLocaleString() + '만' : v.toLocaleString() + '만';
                        return c.dataset.label + ': ' + p;
                    }}
                }}
            }}
        }},
        scales: {{
            x: {{ ticks: {{ color: '#666', maxRotation: 45, maxTicksLimit: 12 }}, grid: {{ color: '#222' }} }},
            y: {{
                ticks: {{
                    color: '#666',
                    callback: function(v) {{
                        const b = Math.floor(v / 10000);
                        return b > 0 ? b + '억' : v.toLocaleString() + '만';
                    }}
                }},
                grid: {{ color: '#222' }}
            }}
        }}
    }}
}});

/* ── 기간 토글 ── */
function setRange(m) {{
    document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(m === 12 ? 'btn-1y' : m === 24 ? 'btn-2y' : 'btn-3y').classList.add('active');
    tc.data.labels = aptLabels.slice(-m);
    tc.data.datasets.forEach((ds, i) => {{
        ds.data = aptDatasets[i].data.slice(-m);
    }});
    tc.update();
}}

/* ── 클릭 인터랙션: 리스트 → 차트 하이라이트 ── */
let activeIdx = -1;

function highlightChart(idx) {{
    const label = document.getElementById('selectedLabel');
    tc.data.datasets.forEach((ds, i) => {{
        if (i === idx) {{
            ds.borderWidth = 3.5;
            ds.borderColor = ds._origColor;
            ds.pointRadius = 3;
            ds.pointBackgroundColor = ds._origColor;
        }} else {{
            ds.borderWidth = 1;
            ds.borderColor = ds._origColor + '1A';
            ds.pointRadius = 0;
        }}
    }});
    label.textContent = aptDatasets[idx].label;
    label.style.color = COLORS[idx];
    label.classList.add('show');
    tc.update();
}}

function resetChart() {{
    const label = document.getElementById('selectedLabel');
    tc.data.datasets.forEach((ds) => {{
        ds.borderWidth = 1.5;
        ds.borderColor = ds._origColor;
        ds.pointRadius = 0;
    }});
    label.classList.remove('show');
    tc.update();
}}

function highlightRows(idx) {{
    document.querySelectorAll('.main-row').forEach((row, i) => {{
        if (i === idx) {{
            row.classList.add('active-row');
            row.classList.remove('dimmed');
        }} else {{
            row.classList.remove('active-row');
            row.classList.add('dimmed');
        }}
    }});
}}

function resetRows() {{
    document.querySelectorAll('.main-row').forEach(row => {{
        row.classList.remove('active-row', 'dimmed');
    }});
}}

function handleRowClick(idx) {{
    if (activeIdx === idx) {{
        activeIdx = -1;
        resetChart();
        resetRows();
    }} else {{
        activeIdx = idx;
        highlightChart(idx);
        highlightRows(idx);
        document.getElementById('chartSection').scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
    }}
    toggleDetail(idx + 1);
}}

function toggleDetail(id) {{
    document.getElementById('detail-' + id).classList.toggle('show');
    document.getElementById('arrow-' + id).classList.toggle('open');
}}
</script>
</body>
</html>'''


# ════════════════════════════════════════
# 메인 실행
# ════════════════════════════════════════

def main():
    print("=" * 60)
    print("  통합 아파트 대시보드 데이터 수집기")
    print("  (전국 구별 TOP 10 + 서울 TOP 20)")
    print("=" * 60 + "\n")

    if not API_KEY or API_KEY == 'YOUR_API_KEY_HERE':
        print("❌ MOLIT_API_KEY가 설정되지 않았습니다!")
        exit(1)
    print(f"✅ API Key: {API_KEY[:8]}...{API_KEY[-4:]}")

    # API 테스트
    test_ym = get_months(1)[0]
    test_url = f"{BASE_URL}?serviceKey={API_KEY}&LAWD_CD=11680&DEAL_YMD={test_ym}&pageNo=1&numOfRows=1"
    try:
        tr = requests.get(test_url, timeout=15)
        rc = re.search(r'<resultCode>(\d+)</resultCode>', tr.text)
        rc_val = rc.group(1) if rc else ''
        if rc_val in ('00', '000'):
            print(f"✅ API 테스트 성공 (강남구 {test_ym})\n")
        else:
            rm = re.search(r'<resultMsg>([^<]+)</resultMsg>', tr.text)
            msg = rm.group(1) if rm else tr.text[:200]
            print(f"❌ API 테스트 실패: {rc_val} - {msg}")
            exit(1)
    except Exception as e:
        print(f"❌ API 연결 실패: {e}")
        exit(1)

    os.makedirs(DATA_DIR, exist_ok=True)

    # ── Step 1: 전 지역 최근 6개월 (한 번에) ──
    months_6 = get_months(6)
    months_6_set = set(months_6)
    recent = fetch_all_recent(months_6)

    if len(recent) == 0:
        print("\n❌ 데이터를 가져오지 못했습니다!")
        exit(1)

    # 서울 데이터 분리
    recent_seoul = [it for it in recent if it['region_code'] in SEOUL_CODES]
    print(f"  서울 데이터: {len(recent_seoul)}건 / 전국: {len(recent)}건\n")

    # ── 히스토리에 필요한 지역코드 파악 ──
    # 전국 구별 TOP 10용 코드
    district_codes = set()
    by_district = defaultdict(list)
    for it in recent:
        key = f"{it['sido']}|{it['sigungu']}"
        by_district[key].append(it)
    for key, items in by_district.items():
        for it in items:
            district_codes.add(it['region_code'])

    # 서울 TOP 20용 코드
    t20_preview = seoul_top20(recent_seoul)
    seoul_history_codes = set(it['region_code'] for it in t20_preview) if t20_preview else set()

    # 합집합 (중복 제거)
    all_history_codes = district_codes | seoul_history_codes
    print(f"  히스토리 필요 지역: {len(all_history_codes)}개 (구별 {len(district_codes)} + 서울 TOP20 {len(seoul_history_codes)} → 합집합 {len(all_history_codes)})\n")

    # ── Step 2: 히스토리 수집 (한 번에) ──
    months_36 = get_months(36)
    months_extra = [m for m in months_36 if m not in months_6_set]
    history = fetch_history(all_history_codes, months_extra)

    # 전체 데이터 = 최근 + 히스토리
    alldata = recent + history
    alldata_seoul = [it for it in alldata if it['region_code'] in SEOUL_CODES]
    print(f"  전체 데이터: {len(alldata)}건 (서울 {len(alldata_seoul)}건)\n")

    # ── Step 3: 대시보드 생성 ──
    print("Step 3: 대시보드 생성\n")

    # 대시보드 1: 전국 구별 TOP 10
    build_district_data(recent, alldata, months_6_set)

    # 대시보드 2: 서울 TOP 20
    build_seoul_html(recent_seoul, alldata_seoul)

    print("\n" + "=" * 60)
    print("  ✅ 모든 대시보드 생성 완료!")
    print("=" * 60)


if __name__ == '__main__':
    main()
