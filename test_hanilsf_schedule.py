"""DB-free stage-two tests (a), (a-prime), (b)-(h), using actual CP-SAT."""
import copy
import importlib.util
import json
import math
import sys
from datetime import datetime

import hanilsf_plan as hp
assert importlib.util.find_spec('hanilsf_schedule') is not None, 'stage-two module not implemented'
import hanilsf_schedule as hs

T0='2026-01-01T00:00:00'
STATE=dict(color_code='WH1N',gsm=100,agri=False)


def fixture(specs):
    # Exact one-hour jobs: public coefficient parameters, no mocked solver.
    rows=[dict(order_id=str(i),item=f'2TEST{gsm}{color}',width=3400,length=1000,rolls=1,
               gsm=gsm,mb_ratio=.05,**kw) for i,(gsm,color,kw) in enumerate(specs)]
    return hp.plan(rows,mr_width_factor=1,time_divisors=(1,{gsm:gsm for gsm,_,_ in specs}))


def solve(p,**kw):
    return hs.schedule(p,t0=T0,machine_state=STATE,**kw)


def verify(r,p):
    assert r['status']=='OPTIMAL' and r['complete']
    assert len(r['jobs'])==sum(len(g['sets']) for g in p['groups'])
    assert len({j['job_id'] for j in r['jobs']})==len(r['jobs'])
    previous=datetime.fromisoformat(T0)
    for j,tr in zip(r['jobs'],r['transitions']):
        start,end=map(datetime.fromisoformat,(j['start'],j['end']))
        assert start>=previous and end>start
        assert (start-previous).total_seconds()/60>=tr['scheduled_minutes']
        assert tr['to']==j['job_id'] and tr['delta_h']>=0
        previous=end
    assert math.isclose(r['total_changeover_h'],sum(t['delta_h'] for t in r['transitions']))
    assert r['total_cr_rolls']==sum(t['cr_rolls'] for t in r['transitions'])
    assert math.isclose(r['total_tardiness_h'],sum(j['tardiness_h'] for j in r['jobs']))
    assert math.isclose(sum(r['mb_kg_by_color'].values()),sum(g['mb_kg'] for g in p['groups']))
    assert r['coefficients_estimated'] and json.dumps(r,allow_nan=False)
    return r


def test_a_weight_buffer():
    p=fixture([(100,'WH1N',{}),(30,'WH1N',{}),(60,'WH1N',{})])
    r=verify(solve(p),p)
    assert [j['gsm'] for j in r['jobs']]==[100,60,30]
    assert r['total_changeover_h']==.375 and r['rise_count']==0
    assert sum(t['scheduled_minutes'] for t in r['transitions'])==23
    print('  (a) unique sequence=100->60->30, transition=0.375h, scheduled=23min, rises=0')


def test_a_prime_direct_drop():
    p=fixture([(100,'WH1N',{}),(30,'WH1N',{})])
    r=verify(solve(p),p)
    assert [j['gsm'] for j in r['jobs']]==[100,30]
    assert r['transitions'][1]['delta_h']==1.5
    print('  (a-prime) 100->30 direct: transition=1.5h, CR=0')


def test_b_light_before_dark():
    p=fixture([(100,'BK1N',{}),(100,'WH1N',{})])
    r=verify(solve(p),p)
    assert [j['color_code'] for j in r['jobs']]==['WH1N','BK1N']
    print('  (b) WH before BK, light->dark=0.83h')


def test_c_black_to_white_cr():
    p=fixture([(100,'WH1N',{})])
    r=hs.schedule(p,t0=T0,machine_state=dict(color_code='BK1N',gsm=100,agri=False))
    verify(r,p)
    assert r['total_cr_rolls']==6 and r['total_changeover_h']==5.5
    print('  (c) unavoidable BK->WH: CR=6 rolls, changeover=5.5h')


def test_d_urgent_deadline():
    p=fixture([(100,'WH1N',{}),(100,'BK1N',dict(urgent=True,due='2026-01-01T02:00:00'))])
    r=verify(solve(p),p)
    assert r['jobs'][0]['color_code']=='BK1N' and r['total_tardiness_h']==0
    print('  (d) urgent BK before WH, tardiness=0h')


def test_e_frozen():
    p=fixture([(100,'WH1N',{}),(60,'WH1N',{}),(30,'WH1N',{})])
    fixed=[dict(job_id=g['item']+':1',start=start) for g,start in zip(p['groups'][:2],['2026-01-01T01:00:00','2026-01-01T03:00:00'])]
    r=verify(solve(p,frozen=fixed),p)
    assert [j['job_id'] for j in r['jobs'][:2]]==[f['job_id'] for f in fixed]
    assert [j['start'] for j in r['jobs'][:2]]==[f['start'] for f in fixed]
    print('  (e) frozen prefix order/start preserved: 01:00, 03:00')


def test_f_release():
    p=fixture([(100,'WH1N',dict(available_from='2026-01-01T04:00:00'))])
    r=verify(solve(p),p)
    assert r['jobs'][0]['start']=='2026-01-01T04:00:00'
    print('  (f) available_from=04:00, start=04:00')


def test_g_blocked():
    p=fixture([(100,'WH1N',{})])
    blocked=[dict(start='2026-01-01T00:30:00',end='2026-01-01T02:00:00')]
    r=verify(solve(p,blocked=blocked),p)
    assert r['jobs'][0]['start']=='2026-01-01T02:00:00'
    print('  (g) blocked 00:30-02:00 respected: start=02:00')


def test_h_invariants_and_errors():
    p=fixture([(100,'WH1N',{}),(60,'WH2N',{}),(30,'UV2N',{})])
    before=copy.deepcopy(p)
    r=verify(solve(p),p)
    assert p==before and r['warnings'] and len(r['mb_kg_by_color'])==3
    from test_hanilsf_plan import fails
    fails(lambda: hs.schedule(p,t0=T0,machine_state={}))
    fails(lambda: solve(p,time_limit=0))
    fails(lambda: solve(p,frozen=[dict(job_id='missing',start=T0)]))
    fails(lambda: solve(p,blocked=[dict(start=T0,end=T0)]))
    fails(lambda: solve(p|dict(complete=False)))
    bad=copy.deepcopy(p);bad['groups'][0]['production_hours']=None
    fails(lambda: solve(bad))
    r=solve(p,time_limit=1e-9)
    assert not r['complete'] and r['status']=='UNKNOWN' and r['jobs']==[]
    r=solve(p,frozen=[dict(job_id=p['groups'][0]['item']+':1',start=T0)],blocked=[dict(start=T0,end='2026-01-01T02:00:00')])
    assert r['status']=='INFEASIBLE' and not r['complete']
    assert solve(hp.plan([]))['jobs']==[]
    assert 'hhhs_db_manager' not in sys.modules and 'hanilsf_optimizer' not in sys.modules
    print('  (h) times/transitions/MB/immutability/validation/UNKNOWN/INFEASIBLE: passed')


def test_rules_override_and_small_oracle():
    import itertools
    import tempfile
    from pathlib import Path
    from test_hanilsf_plan import fails
    p=fixture([(100,'WH1N',{}),(30,'WH1N',{}),(60,'WH1N',{})])
    # Exhaust all six sequences independently, including initial 100g state.
    objectives={}
    for seq in itertools.permutations([100,30,60]):
        pairs=list(zip((100,)+seq,seq))
        change=sum(math.ceil(.0375*max(0,a-b-30)*60-1e-9) for a,b in pairs)
        rises=sum(b>a for a,b in pairs)
        objectives[seq]=(change,180+change,rises)
    best=min(objectives.values())
    assert [seq for seq,cost in objectives.items() if cost==best]==[(100,60,30)]
    assert best==(23,203,0)
    rules=json.loads(Path(hs.__file__).with_name('transition_rules.json').read_text())
    rules['weight']['drop_h_per_gsm']=.075
    with tempfile.TemporaryDirectory(prefix='.plan-test-',dir=Path(__file__).parent) as d:
        path=Path(d)/'rules.json';path.write_text(json.dumps(rules))
        r=verify(solve(p,rules_file=path),p)
        assert r['total_changeover_h']==.75
        rules['weight']['agri_switch_h']=-1
        path.write_text(json.dumps(rules))
        fails(lambda: solve(p,rules_file=path))
    print('  oracle: all 6 permutations confirm unique (a); rules override=0.75h, invalid rule rejected')


def test_unknown_color_no_cheap_detour():
    p=fixture([(100,'ZZ4N',{}),(100,'WH1N',{})])
    state=dict(color_code='BK1N',gsm=100,agri=False)
    r=verify(hs.schedule(p,t0=T0,machine_state=state),p)
    assert r['total_changeover_h']>=5.5
    assert "C-01/C-04: unknown color families ['ZZ']; lightness_order 보완 필요" in r['warnings']
    rules=json.loads(hs.Path(hs.__file__).with_name('transition_rules.json').read_text())
    uv=dict(color_code='ZZ4N',gsm=100,agri=False)
    wh=dict(color_code='WH1N',gsm=100,agri=False)
    detour=hs._transition(state,uv,rules)['delta_h']+hs._transition(uv,wh,rules)['delta_h']
    direct=hs._transition(state,wh,rules)
    assert detour==11 and direct['delta_h']==5.5 and direct['cr_rolls']==6
    assert hs._transition(state,uv,rules)['cr_rolls']==hs._transition(uv,wh,rules)['cr_rolls']==0
    assert hs._transition(uv,uv,rules)['delta_h']==5.5
    print(f"  unknown color: detour={detour}h >= direct=5.5h; schedule={r['total_changeover_h']}h; warning families=['ZZ']")


def test_embedded_rules_without_json():
    import tempfile
    from pathlib import Path
    from unittest.mock import patch
    from test_hanilsf_plan import fails
    p=fixture([(100,'WH1N',{}),(30,'WH1N',{}),(60,'WH1N',{})])
    expected=solve(p)
    with tempfile.TemporaryDirectory(prefix='.plan-test-',dir=Path(__file__).parent) as d:
        missing=Path(d)/'missing_module.py'
        # Change only module-location discovery; neither rename nor remove real JSON.
        with patch.object(hs,'__file__',str(missing)):
            r=verify(solve(p),p)
            assert [j['gsm'] for j in r['jobs']]==[100,60,30]
            assert r['total_changeover_h']==expected['total_changeover_h']==.375
            fails(lambda: solve(p,rules_file=Path(d)/'missing.json'),FileNotFoundError)
            rules=copy.deepcopy(hs.DEFAULT_TRANSITION_RULES)
            rules['weight']['drop_h_per_gsm']=.075
            explicit=Path(d)/'explicit.json';explicit.write_text(json.dumps(rules))
            assert solve(p,rules_file=explicit)['total_changeover_h']==.75
            assert solve(p)['total_changeover_h']==.375
    assert hs.DEFAULT_TRANSITION_RULES==json.loads(Path(hs.__file__).with_name('transition_rules.json').read_text())
    print('  embedded rules: missing adjacent JSON => OPTIMAL, 100->60->30, 0.375h; explicit file precedence, defaults unchanged')


def test_expanded_lightness_order():
    p=fixture([(100,'NT1N',{}),(100,'UV4N',{}),(100,'WH1N',{})])
    r=verify(solve(p),p)
    assert [j['color_code'] for j in r['jobs']]==['WH1N','NT1N','UV4N']
    assert not any('unknown color families' in w for w in r['warnings'])
    assert math.isclose(r['total_changeover_h'],2.66)
    print('  expanded lightness: WH->NT->UV, changeover=2.66h, no unknown-family warning')


def test_heating_cost_and_proof_fields():
    # S-04/S-06: a rise costs heating time (0.005 h/g above 0 g, capped at 0.5 h); drops keep the 30 g threshold.
    rules=json.loads(hs.Path(hs.__file__).with_name('transition_rules.json').read_text())
    lo,hi=dict(color_code='WH1N',gsm=30,agri=False),dict(color_code='WH1N',gsm=60,agri=False)
    up,down=hs._transition(lo,hi,rules),hs._transition(hi,lo,rules)
    assert up['rise_h']==.15 and up['delta_h']==.15 and up['rise']==1 and down['delta_h']==0
    assert hs._transition(dict(color_code='WH1N',gsm=15,agri=False),dict(color_code='WH1N',gsm=140,agri=False),rules)['rise_h']==.5
    p=fixture([(100,'WH1N',{}),(30,'WH1N',{}),(60,'WH1N',{})])
    r=verify(solve(p),p)
    assert [j['gsm'] for j in r['jobs']]==[100,60,30] and r['proven_optimal'] is True and r['status']=='OPTIMAL'
    assert r['gap_changeover_minutes']<1 and r['objective_bound']<=r['objective_value']
    assert set(r['changeover_components_h'])=={'color_h','drop_h','rise_h','agri_h'}
    assert math.isclose(sum(r['changeover_components_h'].values()),r['total_changeover_h'])
    assert all(t['delta_h']==t['color_h']+t['drop_h']+t['rise_h']+t['agri_h'] for t in r['transitions'])
    print('  heating: 30->60 rise=0.15h, 15->140 capped 0.5h, 60->30 drop=0; proof fields present, (a) still unique')


def test_unavoidable_tardiness_still_proven():
    # Two jobs due at t0 cannot both be on time; the solver must still close the bound.
    p=fixture([(100,'WH1N',dict(due=T0)),(100,'WH1N',dict(due=T0)),(60,'BK1N',{})])
    r=verify(solve(p),p)
    assert r['status']=='OPTIMAL' and r['proven_optimal'] and r['total_tardiness_h']>0
    assert r['jobs'][0]['color_code']=='WH1N'   # 같은 규격 두 주문은 1단에서 한 세트(2회)로 묶여 작업 하나가 된다
    print(f"  tardiness: unavoidable {r['total_tardiness_h']}h, still OPTIMAL")


def test_optional_examples_proven_optimal():
    from pathlib import Path
    path=Path(__file__).with_name('cart_examples.json')
    if not path.exists():
        print('  skip examples proof: cart_examples.json missing');return False
    import time
    exs={e['id']:e for e in json.loads(path.read_text())}
    for exid in ('ex3','ex5'):
        rows=[dict(r,order_id=f'E{i}') for i,r in enumerate(exs[exid]['rows'],1)]
        plan=hp.plan(rows,time_limit=20)
        t=time.time();r=hs.schedule(plan,t0=T0,machine_state=STATE,time_limit=120);el=time.time()-t
        assert r['complete'] and r['proven_optimal'],f'{exid} not proven within 120s'
        print(f"  {exid}: {len(r['jobs'])} jobs proven OPTIMAL in {el:.1f}s, changeover={r['total_changeover_h']:.2f}h gap={r['gap_changeover_minutes']:.3f}min")


if __name__=='__main__':
    for name,fn in list(globals().items()):
        if name.startswith('test_'):
            fn();print('ok',name)
